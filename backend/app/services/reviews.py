# 教师复核流：低置信度 AI 错因同步进入教师队列，学生可立即查看并订正。
# 分数和审核通过提醒仍等教师处理后放行。
#
# 学生的学习报告/画像可以选择排除 pending 记录；错题本与订正待办不排除。
from datetime import datetime
import math
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from ..models import Error, Notification, Question, Step, Submission, SubmissionReview

PENDING = "pending"
APPROVED = "approved"
REVIEW_THRESHOLD = 0.60


def create_pending_review(db: Session, submission: Submission) -> SubmissionReview:
    """实时批改入口产生新提交后调用：建一条 pending 审核行（幂等，已有行不覆盖）。"""
    row = db.query(SubmissionReview).filter(
        SubmissionReview.submission_id == submission.id
    ).first()
    if row is None:
        row = SubmissionReview(submission_id=submission.id, status=PENDING)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def visual_confidence_signals(image_confidence, visual_steps) -> List[float]:
    """提取视觉模型的整图与逐步判断置信度，供审核阈值共用。"""
    raw_values = [image_confidence]
    for step in visual_steps or []:
        if isinstance(step, dict) and str(step.get("text", "")).strip():
            # 与 diagnose_visual_submission 一致：缺少步骤置信度时按 0.5 处理。
            raw_values.append(step.get("confidence", 0.5))

    values = []
    for raw in raw_values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        values.append(max(0.0, min(1.0, value)))
    return values


def assignment_accuracy_context(
    db: Session, submission: Submission
) -> Optional[Tuple[List[Submission], int, int, bool]]:
    """返回同一学生、同一作业、同一学科各题最新提交的步骤正确率统计。

    complete 表示该作业该学科的每道题都已有批改完成的提交。审核阈值使用
    已完成整份作业后的累计正确率，避免学生只做了一部分时过早触发作业级审核。
    """
    question = submission.question or db.query(Question).filter(
        Question.id == submission.question_id
    ).first()
    if question is None:
        return None

    question_ids = [row[0] for row in db.query(Question.id).filter(
        Question.assignment_id == question.assignment_id,
        Question.subject == question.subject,
    ).all()]
    if not question_ids:
        return None

    submissions = db.query(Submission).filter(
        Submission.student_id == submission.student_id,
        Submission.question_id.in_(question_ids),
        Submission.status == "graded",
    ).order_by(Submission.submitted_at.asc(), Submission.id.asc()).all()
    latest_by_question = {item.question_id: item for item in submissions}
    latest_submissions = [
        latest_by_question[qid]
        for qid in question_ids
        if qid in latest_by_question
    ]
    complete = len(latest_submissions) == len(question_ids)
    submission_ids = [item.id for item in latest_submissions]
    statuses = db.query(Step.status).filter(
        Step.submission_id.in_(submission_ids), Step.seq >= 1
    ).all() if submission_ids else []
    correct = sum(1 for row in statuses if row[0] == "ok")
    return latest_submissions, correct, len(statuses), complete


def review_reasons(db: Session, submission: Submission,
                   confidence_signals: Iterable[float] = ()) -> List[str]:
    """返回触发教师复核的原因，统一步骤率、错因和视觉置信度口径。"""
    reasons = []
    step_statuses = [row[0] for row in db.query(Step.status).filter(
        Step.submission_id == submission.id,
        Step.seq >= 1,
    ).all()]
    if step_statuses:
        correct = sum(1 for value in step_statuses if value == "ok")
        accuracy = correct / len(step_statuses)
        if accuracy < REVIEW_THRESHOLD:
            reasons.append("作答步骤正确率低于 60%")

    assignment_context = assignment_accuracy_context(db, submission)
    if assignment_context:
        _, assignment_correct, assignment_total, assignment_complete = assignment_context
        if (assignment_complete and assignment_total > 0
                and assignment_correct / assignment_total < REVIEW_THRESHOLD):
            reasons.append("本次作业累计正确率低于 60%")

    confidences = [
        float(row[0])
        for row in db.query(Error.confidence)
        .filter(Error.submission_id == submission.id)
        .all()
    ]
    if any(not math.isfinite(value) or value < REVIEW_THRESHOLD for value in confidences):
        reasons.append("错因判断置信度低于 60%")

    normalized_signals = []
    for raw in confidence_signals:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        normalized_signals.append(max(0.0, min(1.0, value)))
    if any(value < REVIEW_THRESHOLD for value in normalized_signals):
        reasons.append("图片或步骤判断置信度低于 60%")
    return reasons


def needs_teacher_review(db: Session, submission: Submission,
                         confidence_signals: Iterable[float] = ()) -> bool:
    """单题正确率、完整作业累计正确率、错因置信度或视觉置信度低于 60% 时送审。

    正确率按 seq >= 1 的作答步骤计算；作业累计率在同学科题目全部提交后计算。
    视觉路径同时检查整图和每步判断置信度。
    """
    return bool(review_reasons(db, submission, confidence_signals))


def create_review_if_needed(db: Session, submission: Submission,
                            confidence_signals: Iterable[float] = ()) -> Optional[SubmissionReview]:
    """按作答与视觉置信度决定是否建立待审核记录。"""
    if not needs_teacher_review(db, submission, confidence_signals):
        return None
    row = create_pending_review(db, submission)

    assignment_context = assignment_accuracy_context(db, submission)
    if assignment_context:
        latest_submissions, correct, total, complete = assignment_context
        if complete and total > 0 and correct / total < REVIEW_THRESHOLD:
            # 作业整体低于阈值时，把该学生本学科各题的最新提交一起送审，
            # 教师窗口能看到完整作业，卡片正确率也按整份作业计算。
            for item in latest_submissions:
                create_pending_review(db, item)
    return row


def review_status(db: Session, submission_id: int) -> str:
    """单条提交的审核状态：无审核行 = approved（历史/种子数据口径）。"""
    row = db.query(SubmissionReview).filter(
        SubmissionReview.submission_id == submission_id
    ).first()
    if row is None:
        return APPROVED
    return row.status


def review_status_map(db: Session, submission_ids: Iterable[int]) -> dict:
    """批量查审核状态，返回 {submission_id: status}，无行的不出现在 dict 里。"""
    ids = list(submission_ids)
    if not ids:
        return {}
    rows = (
        db.query(SubmissionReview)
        .filter(SubmissionReview.submission_id.in_(ids))
        .all()
    )
    return {r.submission_id: r.status for r in rows}


def pending_submission_ids(db: Session, student_id: Optional[int] = None) -> Set[int]:
    """全部（或某个学生的）待审核提交 id 集合，供分数/统计等口径筛选。"""
    query = (
        db.query(SubmissionReview.submission_id)
        .filter(SubmissionReview.status == PENDING)
    )
    if student_id is not None:
        query = query.join(
            Submission, Submission.id == SubmissionReview.submission_id
        ).filter(Submission.student_id == student_id)
    return {row[0] for row in query.all()}


def visible_submissions(db: Session, submissions: List[Submission]) -> List[Submission]:
    """从提交列表中滤掉待审核的（学生侧统计/报告/画像共用）。"""
    if not submissions:
        return submissions
    pending = pending_submission_ids(db, submissions[0].student_id)
    return [s for s in submissions if s.id not in pending]


def approve_submission(db: Session, submission: Submission, teacher,
                       *, notify: bool = True) -> SubmissionReview:
    """把一条提交置为 approved 并给学生发审核通过提醒（幂等：
    已 approved 的不重复发提醒）。返回审核行。"""
    row = db.query(SubmissionReview).filter(
        SubmissionReview.submission_id == submission.id
    ).first()
    if row is None:
        row = SubmissionReview(submission_id=submission.id)
        db.add(row)
    was_pending = row.status == PENDING
    row.status = APPROVED
    row.reviewed_by = teacher.id
    row.reviewed_at = datetime.now()
    if notify and was_pending:
        title = ""
        if submission.question is not None:
            assignment = submission.question.assignment
            title = assignment.title if assignment else ""
        db.add(Notification(
            user_id=submission.student_id,
            type="review_approved",
            content=(
                f"{teacher.name}已审核通过你《{title}》的批改结果，"
                "去看看老师的诊断吧。"
            ),
            related_submission_id=submission.id,
        ))
    db.commit()
    db.refresh(row)
    return row


def pending_reviews(db: Session) -> List[Submission]:
    """教师端待审核队列：pending 的提交按提交时间正序（先交先审）。"""
    rows = (
        db.query(SubmissionReview)
        .filter(SubmissionReview.status == PENDING)
        .all()
    )
    pending_ids = [r.submission_id for r in rows]
    if not pending_ids:
        return []
    subs = (
        db.query(Submission)
        .filter(Submission.id.in_(pending_ids))
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    return subs
