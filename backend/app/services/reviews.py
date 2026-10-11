# 教师复核流：低置信度 AI 错因同步进入教师队列，学生可立即查看并订正。
# 分数和审核通过提醒仍等教师处理后放行。
#
# 学生的学习报告/画像可以选择排除 pending 记录；错题本与订正待办不排除。
from datetime import datetime
from typing import Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from ..models import Error, Notification, Step, Submission, SubmissionReview

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


def needs_teacher_review(db: Session, submission: Submission) -> bool:
    """本次作答正确率或错因置信度低于 60% 时送入教师队列。

    正确率按有效作答步骤计算；错因置信度按错误记录计算。任一条件触发，
    就审核整份提交。没有作答步骤和错误记录的提交不需要审核。
    """
    step_statuses = [row[0] for row in db.query(Step.status).filter(
        Step.submission_id == submission.id,
        Step.seq >= 1,
    ).all()]
    if step_statuses:
        accuracy = sum(1 for value in step_statuses if value == "ok") / len(step_statuses)
        if accuracy < REVIEW_THRESHOLD:
            return True

    confidences = [
        float(row[0])
        for row in db.query(Error.confidence)
        .filter(Error.submission_id == submission.id)
        .all()
    ]
    return any(value < REVIEW_THRESHOLD for value in confidences)


def create_review_if_needed(db: Session, submission: Submission) -> Optional[SubmissionReview]:
    """按作答正确率和错因置信度决定是否建立待审核记录。"""
    if not needs_teacher_review(db, submission):
        return None
    return create_pending_review(db, submission)


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
