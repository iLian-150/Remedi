# 提交规则与延迟批改（v0.13.1）：
# - 默认每道题只能提交一次（教师在发布时未勾选「允许修改」时）。
# - 勾选 allow_revision 的作业：截止前学生可反复修改，每次修改落一份
#   status="deferred" 的数学提交或作文记录，截止前不做 AI 批改/评分；
#   截止时间到后由 grade_due() 只处理每道题的最后一份，并将旧版本标为
#   superseded。数学作答进入诊断与教师审核流程，作文复用原作文记录评分。
# - 没设截止时间的 allow_revision 作业不延迟（无截止可等），按立即批改 +
#   允许覆盖走（lock 检查放行、旧提交保留为历史，最新一份生效）。
import json
import logging
import mimetypes
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, true
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import (
    Assignment,
    AssignmentExt,
    AssignmentSetting,
    Error,
    Essay,
    Question,
    Step,
    Submission,
    SubmissionImage,
    User,
)
from .confidence import normalize_confidence
from .diagnosis import diagnose_submission, diagnose_visual_submission
from . import reviews as review_svc
from .app_time import deadline_now, normalize_deadline
from .providers import get_provider

DEFERRED = "deferred"
SUPERSEDED = "superseded"
logger = logging.getLogger(__name__)
def _lock_question_for_submission(db: Session, question: Question) -> None:
    """Serialize the final duplicate check and insert across API workers."""
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        exists = db.query(Question.id).filter_by(id=question.id).with_for_update().first()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在。")
        return

    raw_connection = connection.connection.driver_connection
    if not raw_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        return
    try:
        # SQLite has no row-level FOR UPDATE. A no-op write reserves its writer
        # slot; this also upgrades sessions that already read during validation.
        connection.exec_driver_sql(
            "UPDATE questions SET id = id WHERE id = ?", (question.id,),
        )
    except OperationalError as exc:
        error_code = getattr(exc.orig, "sqlite_errorcode", 0) or 0
        if error_code & 0xFF not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
        # WAL readers can hold an obsolete snapshot that cannot be upgraded.
        # Restart after the competing writer commits, then re-check under lock.
        db.rollback()
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def lock_and_assert_can_submit(
    db: Session,
    student: User,
    question: Question,
    *,
    received_at: Optional[datetime] = None,
    essay: bool = False,
) -> bool:
    """Recheck submission rules while holding the DB write/row lock until commit."""
    _lock_question_for_submission(db, question)
    checker = assert_can_submit_essay if essay else assert_can_submit
    return checker(db, student, question, received_at=received_at)


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
    return bool(deadline and deadline_now() < deadline)


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
    now = normalize_deadline(received_at) if received_at is not None else deadline_now()
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


def assert_can_submit_essay(
    db: Session,
    student: User,
    question: Question,
    *,
    received_at: Optional[datetime] = None,
) -> bool:
    """Apply the same one-submit/revision window to essay questions.

    Returns whether scoring must wait until the assignment deadline. Essay
    attempts live in their own table, so they cannot use the math Submission
    lookup in ``assert_can_submit``.
    """
    now = normalize_deadline(received_at) if received_at is not None else deadline_now()
    settings = (
        db.query(
            AssignmentSetting.allow_revision.label("allow_revision"),
            AssignmentExt.deadline.label("deadline"),
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
        .filter(Assignment.id == question.assignment_id)
        .first()
    )
    revision_allowed = bool(settings and settings.allow_revision)
    deadline = settings.deadline if settings else None
    latest = (
        db.query(Essay.id, Essay.status)
        .filter(Essay.student_id == student.id, Essay.question_id == question.id)
        .order_by(Essay.submitted_at.desc(), Essay.id.desc())
        .first()
    )
    deferred_window = bool(revision_allowed and deadline and now < deadline)

    if revision_allowed and deadline is not None and now >= deadline:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "作业已过截止时间，不能继续修改；已提交内容会自动批改。"
            if latest and latest.status == DEFERRED
            else "作业已过截止时间，不能再提交。",
        )
    if latest is None:
        return deferred_window
    if latest.status == DEFERRED and deferred_window:
        return True
    if revision_allowed and deadline is None:
        return False
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
    before_save=None,
) -> Submission:
    """落一份延迟提交：只存原始步骤（seq 从 1 开始，status=deferred 占位），不诊断。"""
    if before_save is not None:
        before_save()
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
    """批改到期的数学作答并评分到期作文，返回成功处理的记录数。"""
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        return _grade_due_batch(db) + _grade_due_essays(db)
    finally:
        db.expire_on_commit = expire_on_commit


def _enqueue_due_reviews(
    db: Session,
    submissions: List[Submission],
    confidence_signals_by_submission: dict[int, List[float]],
) -> None:
    """截止批改结算整份作业，只按总分是否低于 60 分生成审核项。"""
    if not submissions:
        return
    seen = set()
    for submission in submissions:
        if submission.question is None:
            continue
        key = (submission.student_id, submission.question.assignment_id)
        if key in seen:
            continue
        seen.add(key)
        review_svc.refresh_assignment_review(
            db, submission, force_complete=True, commit=False,
        )


def _grade_due_batch(db: Session) -> int:
    """到期统一批改：扫所有 allow_revision 作业，截止已过的，把每道题
    每个学生的最后一次延迟提交批改掉；返回本次批改的提交数。
    幂等：已批改的提交不再是 deferred，不会重复处理。"""
    now = deadline_now()
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
                    from ..agent.subjects import build_subject_context
                    rag_context = build_subject_context(
                        db, question.subject,
                        f"{question.knowledge_point} {question.stem} {question.standard_answer or ''}",
                    )
                    vision = get_provider().diagnose_homework_image(
                        image_bytes,
                        content_type,
                        f"学科：{question.subject}\n题目：{question.stem}\n"
                        f"教师参考答案或步骤：{question.standard_answer or '未提供'}\n{rag_context}",
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


def _grade_due_essays(db: Session) -> int:
    """Score only each student's latest deferred essay after its deadline."""
    now = deadline_now()
    due_essays = (
        db.query(Essay, Question.stem)
        .join(Question, Question.id == Essay.question_id)
        .join(AssignmentSetting, AssignmentSetting.assignment_id == Question.assignment_id)
        .join(AssignmentExt, AssignmentExt.assignment_id == Question.assignment_id)
        .filter(
            AssignmentSetting.allow_revision.is_(True),
            AssignmentExt.deadline <= now,
            Essay.status == DEFERRED,
        )
    )

    def load_batch(cursor=None):
        query = due_essays
        if cursor is not None:
            submitted_at, essay_id = cursor
            query = query.filter(or_(
                Essay.submitted_at < submitted_at,
                and_(Essay.submitted_at == submitted_at, Essay.id < essay_id),
            ))
        return query.order_by(
            Essay.submitted_at.desc(), Essay.id.desc(),
        ).limit(500).all()

    batch = load_batch()
    if not batch:
        return 0

    graded = 0
    seen_pairs = set()
    cursor = None
    while batch:
        last_essay = batch[-1][0]
        cursor = (last_essay.submitted_at, last_essay.id)
        for essay, prompt in batch:
            pair = (essay.student_id, essay.question_id)
            if pair in seen_pairs:
                essay.status = SUPERSEDED
                continue
            seen_pairs.add(pair)
            try:
                result = get_provider().score_essay(text=essay.text, prompt=prompt)
            except Exception:
                logger.exception("延迟作文评分失败，essay_id=%s", essay.id)
                continue
            essay.scores_json = json.dumps(result["scores"], ensure_ascii=False)
            essay.grammar_issues_json = json.dumps(
                result.get("grammar_issues", []), ensure_ascii=False,
            )
            essay.overall_comment = result.get("overall", "")
            essay.status = "submitted"
            graded += 1
        batch = load_batch(cursor)

    db.commit()
    return graded
