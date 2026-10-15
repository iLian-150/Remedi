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
from sqlalchemy import and_, case, func, or_, true
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import (
    Assignment,
    AssignmentExt,
    AssignmentSetting,
    Error,
    Question,
    Step,
    Submission,
    SubmissionImage,
    User,
)
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
    latest_submission = (
        db.query(
            Submission.id.label("submission_id"),
            Submission.status.label("submission_status"),
        )
        .filter(
            Submission.student_id == student.id,
            Submission.question_id == question.id,
        )
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(1)
        .subquery()
    )
    submission_rules = (
        db.query(
            AssignmentSetting.allow_revision.label("allow_revision"),
            AssignmentExt.deadline.label("deadline"),
            latest_submission.c.submission_id.label("latest_submission_id"),
            latest_submission.c.submission_status.label("latest_submission_status"),
        )
        .select_from(Assignment)
        .outerjoin(
            AssignmentSetting,
            AssignmentSetting.assignment_id == Assignment.id,
        )
        .outerjoin(
            AssignmentExt,
            AssignmentExt.assignment_id == Assignment.id,
        )
        .outerjoin(latest_submission, true())
        .filter(Assignment.id == question.assignment_id)
        .first()
    )
    revision_allowed = (
        bool(submission_rules.allow_revision) if submission_rules else False
    )
    deadline = submission_rules.deadline if submission_rules else None
    has_latest_submission = bool(
        submission_rules and submission_rules.latest_submission_id is not None
    )
    latest_status = (
        submission_rules.latest_submission_status if submission_rules else None
    )
    deferred_window = bool(revision_allowed and deadline is not None and now < deadline)

    if revision_allowed and deadline is not None and now >= deadline:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "作业已过截止时间，不能继续修改；已提交内容会自动批改。"
            if has_latest_submission and latest_status == DEFERRED
            else "作业已过截止时间，不能再提交。",
        )

    if not has_latest_submission:
        return deferred_window
    if latest_status == DEFERRED:
        if deferred_window:
            return True  # 截止前修改：新的延迟提交会成为最新一份
    if revision_allowed and deadline is None:
        return False  # 无截止的允许修改作业：立即批改口径，继续放行
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "这道题已经提交过了，每道题只能提交一次。",
    )


def create_deferred(
    db: Session,
    student: User,
    question: Question,
    step_texts: List[str],
    *,
    image_path: Optional[str] = None,
    image_name: Optional[str] = None,
) -> Submission:
    """落一份延迟提交：只存原始步骤（seq 从 1 开始，status=deferred 占位），不诊断。"""
    submission = Submission(student_id=student.id, question_id=question.id, status=DEFERRED)
    db.add(submission)
    db.flush()
    for i, raw in enumerate(step_texts, start=1):
        db.add(Step(submission_id=submission.id, seq=i, text=raw, status=DEFERRED))
    if image_path:
        db.add(SubmissionImage(
            submission_id=submission.id,
            file_path=image_path,
            file_name=(image_name or "作业照片")[:255],
        ))
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
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


def _enqueue_due_reviews(
    db: Session,
    submissions: List[Submission],
    confidence_signals_by_submission: dict[int, List[float]],
) -> None:
    """批量计算本轮延迟批改的复核条件，避免逐提交重算整份作业上下文。"""
    if not submissions:
        return

    assignment_contexts = review_svc.assignment_accuracy_contexts(db, submissions)
    step_counts_by_submission = {}
    low_confidence_by_submission = {}
    submission_ids = [submission.id for submission in submissions]
    low_confidence = review_svc.low_error_confidence_predicate()
    for start in range(0, len(submission_ids), 500):
        id_chunk = submission_ids[start:start + 500]
        batch_submission_ids = (
            db.query(Submission.id.label("submission_id"))
            .filter(Submission.id.in_(id_chunk))
            .cte("batch_submission_ids")
        )
        step_counts = (
            db.query(
                Step.submission_id.label("submission_id"),
                func.sum(case((Step.status == "ok", 1), else_=0)).label(
                    "correct_steps"
                ),
                func.count(Step.id).label("total_steps"),
            )
            .join(
                batch_submission_ids,
                batch_submission_ids.c.submission_id == Step.submission_id,
            )
            .filter(
                Step.seq >= 1,
                Step.status.in_(("ok", "error", "unparseable")),
            )
            .group_by(Step.submission_id)
            .subquery()
        )
        error_confidences = (
            db.query(
                Error.submission_id.label("submission_id"),
                func.max(case((low_confidence, 1), else_=0)).label(
                    "has_low_confidence"
                ),
            )
            .join(
                batch_submission_ids,
                batch_submission_ids.c.submission_id == Error.submission_id,
            )
            .group_by(Error.submission_id)
            .subquery()
        )
        summary_rows = db.query(
            batch_submission_ids.c.submission_id,
            step_counts.c.correct_steps,
            step_counts.c.total_steps,
            error_confidences.c.has_low_confidence,
        ).outerjoin(
            step_counts,
            step_counts.c.submission_id == batch_submission_ids.c.submission_id,
        ).outerjoin(
            error_confidences,
            error_confidences.c.submission_id == batch_submission_ids.c.submission_id,
        ).all()
        for (
            submission_id,
            correct_steps,
            total_steps,
            has_low_confidence,
        ) in summary_rows:
            step_counts_by_submission[submission_id] = (
                int(correct_steps or 0), int(total_steps or 0)
            )
            low_confidence_by_submission[submission_id] = bool(
                has_low_confidence
            )

    submissions_to_review = {}
    for submission in submissions:
        question = submission.question
        context = (
            assignment_contexts.get((submission.student_id, question.assignment_id))
            if question is not None else None
        )
        reasons = review_svc.review_reasons(
            db,
            submission,
            confidence_signals_by_submission.get(submission.id, []),
            assignment_context=context,
            step_counts=step_counts_by_submission.get(submission.id, (0, 0)),
            has_low_error_confidence=low_confidence_by_submission.get(
                submission.id, False
            ),
        )
        if not reasons:
            continue

        targets = [submission]
        if context:
            latest_submissions, correct, total = context
            if total > 0 and correct / total < review_svc.REVIEW_THRESHOLD:
                targets = list(latest_submissions)
                latest_ids = {item.id for item in targets}
                if submission.id not in latest_ids:
                    targets.append(submission)
        submissions_to_review.update({
            item.id: item for item in targets
        })

    if submissions_to_review:
        review_svc.create_pending_reviews(db, submissions_to_review.values())


def _grade_due_batch(db: Session) -> int:
    """到期统一批改：扫所有 allow_revision 作业，截止已过的，把每道题
    每个学生的最后一次延迟提交批改掉；返回本次批改的提交数。
    幂等：已批改的提交不再是 deferred，不会重复处理。"""
    now = datetime.now()
    deferred_query = (
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
    )

    def load_batch(cursor=None):
        query = deferred_query
        if cursor is not None:
            submitted_at, submission_id = cursor
            query = query.filter(or_(
                Submission.submitted_at < submitted_at,
                and_(
                    Submission.submitted_at == submitted_at,
                    Submission.id < submission_id,
                ),
            ))
        return query.order_by(
            Submission.submitted_at.desc(), Submission.id.desc()
        ).limit(500).all()

    batch = load_batch()
    if not batch:
        return 0

    graded = 0
    seen_pairs = set()
    graded_for_review = []
    confidence_signals_by_submission = {}
    cursor = None
    while batch:
        last = batch[-1]
        cursor = (last.submitted_at, last.id)
        latest_batch = []
        for sub in batch:
            pair = (sub.student_id, sub.question_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            latest_batch.append(sub)
        if not latest_batch:
            for sub in batch:
                sub.status = SUPERSEDED  # 同题更早的修改版本不批改
            batch = load_batch(cursor)
            continue

        latest_ids = {sub.id for sub in latest_batch}
        submission_ids = [submission.id for submission in latest_batch]
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
            if sub.id not in latest_ids:
                sub.status = SUPERSEDED  # 同题更早的修改版本不批改
                continue

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
            graded_for_review.append(graded_sub)
            confidence_signals_by_submission[graded_sub.id] = confidence_signals
            graded += 1

        batch = load_batch(cursor)
    _enqueue_due_reviews(
        db, graded_for_review, confidence_signals_by_submission
    )
    db.commit()
    return graded
