# 提交规则与延迟批改（v0.13.1）：
# - 默认每道题只能提交一次（教师在发布时未勾选「允许修改」时）。
# - 勾选 allow_revision 的作业：截止前学生可反复修改，每次修改落一份
#   status="deferred" 的提交（只存原始步骤，不诊断、不建审核行）；
#   截止时间到后由 grade_due() 把每道题的最后一次延迟提交统一批改
#   （复用原提交行走 diagnose_submission，再进教师审核队列），
#   被覆盖的旧延迟提交标 superseded 不再处理。
# - 没设截止时间的 allow_revision 作业不延迟（无截止可等），按立即批改 +
#   允许覆盖走（lock 检查放行、旧提交保留为历史，最新一份生效）。
import logging
import mimetypes
import os
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import AssignmentExt, AssignmentSetting, Question, Step, Submission, SubmissionImage, User
from .confidence import normalize_confidence
from .diagnosis import diagnose_submission, diagnose_visual_submission
from . import reviews as review_svc
from .providers import get_provider

DEFERRED = "deferred"
SUPERSEDED = "superseded"
logger = logging.getLogger(__name__)


def allow_revision(db: Session, assignment_id: int) -> bool:
    setting = (
        db.query(AssignmentSetting)
        .filter(AssignmentSetting.assignment_id == assignment_id)
        .first()
    )
    return bool(setting.allow_revision) if setting else False


def assignment_deadline(db: Session, assignment_id: int) -> Optional[datetime]:
    ext = db.query(AssignmentExt).filter(AssignmentExt.assignment_id == assignment_id).first()
    return ext.deadline if ext else None


def is_deferred_mode(db: Session, assignment_id: int) -> bool:
    """当前是否处于「只收不改（批）」窗口：开了允许修改、设了截止、且还没到期。"""
    if not allow_revision(db, assignment_id):
        return False
    deadline = assignment_deadline(db, assignment_id)
    return bool(deadline and datetime.now() < deadline)


def latest_submission(db: Session, student_id: int, question_id: int) -> Optional[Submission]:
    return (
        db.query(Submission)
        .filter(Submission.student_id == student_id, Submission.question_id == question_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .first()
    )


def assert_can_submit(
    db: Session,
    student: User,
    question: Question,
    *,
    received_at: Optional[datetime] = None,
) -> bool:
    """提交锁定：已有生效提交且作业不允许（或已过可修改窗口）→ 拒绝再交。

    返回值表示这次提交是否应进入截止前的延迟批改窗口。使用请求接收时间判定，
    避免视觉识别或逐步诊断耗时跨过截止点后改变这次提交的处理方式。

    allow_revision 且有截止时间的作业：截止前接收的首次提交进入 deferred；
    只有最新提交仍为 deferred 时才允许在截止前继续修改。截止后拒绝首次提交
    和修改。无截止时间的允许修改作业沿用立即批改口径。"""
    now = received_at or datetime.now()
    revision_allowed = allow_revision(db, question.assignment_id)
    deadline = assignment_deadline(db, question.assignment_id)
    deferred_window = bool(revision_allowed and deadline is not None and now < deadline)
    latest = latest_submission(db, student.id, question.id)

    if revision_allowed and deadline is not None and now >= deadline:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "作业已过截止时间，不能继续修改；已提交内容会自动批改。"
            if latest is not None and latest.status == DEFERRED
            else "作业已过截止时间，不能再提交。",
        )

    if latest is None:
        return deferred_window
    if latest.status == DEFERRED:
        if deferred_window:
            return True  # 截止前修改：新的延迟提交会成为最新一份
    if revision_allowed and deadline is None:
        return False  # 无截止的允许修改作业：立即批改口径，继续放行
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "这道题已经提交过了，每道题只能提交一次。",
    )


def create_deferred(db: Session, student: User, question: Question, step_texts: List[str]) -> Submission:
    """落一份延迟提交：只存原始步骤（seq 从 1 开始，status=deferred 占位），不诊断。"""
    submission = Submission(student_id=student.id, question_id=question.id, status=DEFERRED)
    db.add(submission)
    db.flush()
    for i, raw in enumerate(step_texts, start=1):
        db.add(Step(submission_id=submission.id, seq=i, text=raw, status=DEFERRED))
    db.commit()
    db.refresh(submission)
    return submission


def deferred_out(submission: Submission) -> dict:
    """延迟提交的 DiagnosisOut 形态：结论为空，status/review_status 均为 deferred。"""
    return {
        "submission_id": submission.id,
        "question_id": submission.question_id,
        "status": DEFERRED,
        "first_error_seq": None,
        "steps": [],
        "errors": [],
        "follow_up_question": None,
        "review_status": DEFERRED,
        "score": None,
    }


def grade_due(db: Session) -> int:
    """在本次批量任务期间保留预加载对象，避免诊断提交后逐项重新读取。"""
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        return _grade_due_batch(db)
    finally:
        db.expire_on_commit = expire_on_commit


def _grade_due_batch(db: Session) -> int:
    """到期统一批改：扫所有 allow_revision 作业，截止已过的，把每道题
    每个学生的最后一次延迟提交批改掉；返回本次批改的提交数。
    幂等：已批改的提交不再是 deferred，不会重复处理。"""
    now = datetime.now()
    deferred = (
        db.query(Submission)
        .join(Question, Question.id == Submission.question_id)
        .join(AssignmentSetting, AssignmentSetting.assignment_id == Question.assignment_id)
        .join(AssignmentExt, AssignmentExt.assignment_id == Question.assignment_id)
        .options(
            joinedload(Submission.student),
            joinedload(Submission.question),
        )
        .filter(
            AssignmentSetting.allow_revision.is_(True),
            AssignmentExt.deadline <= now,
            Submission.status == DEFERRED,
        )
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .all()
    )
    if not deferred:
        return 0

    graded = 0
    seen_pairs = set()
    for batch_start in range(0, len(deferred), 500):
        batch = deferred[batch_start:batch_start + 500]
        submission_ids = [submission.id for submission in batch]
        steps_by_submission = {}
        for submission_id, step_text in db.query(
            Step.submission_id, Step.text
        ).filter(
            Step.submission_id.in_(submission_ids), Step.seq >= 1
        ).order_by(Step.submission_id.asc(), Step.seq.asc()).all():
            steps_by_submission.setdefault(submission_id, []).append(step_text)
        images_by_submission = dict(
            db.query(SubmissionImage.submission_id, SubmissionImage.file_path)
            .filter(SubmissionImage.submission_id.in_(submission_ids))
            .all()
        )

        for sub in batch:
            pair = (sub.student_id, sub.question_id)
            if pair in seen_pairs:
                sub.status = SUPERSEDED  # 同题更早的修改版本不批改
                continue
            seen_pairs.add(pair)

            student = sub.student
            question = sub.question
            step_texts = steps_by_submission.get(sub.id, [])
            if student is None or question is None or not step_texts:
                sub.status = SUPERSEDED
                continue

            image_file_path = images_by_submission.get(sub.id)
            confidence_signals = []
            if image_file_path is not None:
                image_name = os.path.basename(image_file_path)
                image_path = os.path.join(settings.UPLOAD_DIR, image_name)
                try:
                    with open(image_path, "rb") as image_file:
                        image_bytes = image_file.read()
                    content_type = mimetypes.guess_type(image_name)[0] or "image/jpeg"
                    vision = get_provider().diagnose_homework_image(
                        image_bytes,
                        content_type,
                        f"学科：{question.subject}\n题目：{question.stem}\n"
                        f"教师参考答案或步骤：{question.standard_answer or '未提供'}",
                    )
                except Exception:
                    # 模型或文件暂时不可用时保留 deferred 状态，下轮继续重试。
                    logger.exception("延迟作业视觉批改失败，submission_id=%s", sub.id)
                    continue
                visual_steps = vision.get("steps", [])
                if vision.get("needs_image_review") or normalize_confidence(vision.get("confidence", 0.0)) < 0.45:
                    # 截止时图片仍无法确认，交由教师看原图复核，避免永久卡在延迟态。
                    visual_steps = [{
                        "text": text,
                        "result": "uncertain",
                        "confidence": 0.3,
                        "error_type": "无法解析",
                        "detail": "截止后视觉模型仍无法可靠辨认该作答，已提交教师查看原图复核。",
                    } for text in step_texts]
                elif not vision.get("student_work_detected", bool(visual_steps)) or not visual_steps:
                    visual_steps = [{
                        "text": text,
                        "result": "uncertain",
                        "confidence": 0.3,
                        "error_type": "无法解析",
                        "detail": "图片中未能确认学生作答，已提交教师查看原图复核。",
                    } for text in step_texts]
                confidence_signals = review_svc.visual_confidence_signals(
                    vision.get("confidence", 0.0), visual_steps
                )
                graded_sub, _, _ = diagnose_visual_submission(
                    db, student, question, visual_steps, reuse=sub
                )
            else:
                graded_sub, _, _ = diagnose_submission(
                    db, student, question, step_texts, reuse=sub
                )
            review_svc.create_review_if_needed(
                db, graded_sub, confidence_signals=confidence_signals
            )
            graded += 1
    db.commit()
    return graded
