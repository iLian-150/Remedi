"""教师明日讲评重点与讲后追踪，按授权提交聚合，不调用模型做统计。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Error, Question, Submission, SubmissionReview, TeacherTeachingFocus
from .teacher_scope import teacher_submission_ids


def scoped_attempts(db: Session, teacher):
    """已批改且审核放行的提交，同一题各知识点的多个错误步骤只计算一次。"""
    return db.query(Submission).join(Question, Question.id == Submission.question_id).outerjoin(
        SubmissionReview, SubmissionReview.submission_id == Submission.id,
    ).filter(
        Submission.id.in_(teacher_submission_ids(db, teacher)),
        Submission.status == "graded",
        (SubmissionReview.status.is_(None) | (SubmissionReview.status != "pending")),
    )


def knowledge_point_stats(db: Session, teacher):
    base = scoped_attempts(db, teacher)
    columns = [Question.subject.label("subject"), Question.knowledge_point.label("knowledge_point"),
               Submission.id.label("submission_id"), Submission.student_id.label("student_id")]
    attempts = base.with_entities(*columns).filter(func.trim(Question.knowledge_point) != "")
    errors = base.join(Error, Error.submission_id == Submission.id).with_entities(
        Question.subject.label("subject"), Error.knowledge_point.label("knowledge_point"),
        Submission.id.label("submission_id"), Submission.student_id.label("student_id"),
    ).filter(func.trim(Error.knowledge_point) != "")
    pairs = attempts.union(errors).subquery()
    has_error = db.query(Error.id).filter(
        Error.submission_id == pairs.c.submission_id,
        Error.knowledge_point == pairs.c.knowledge_point,
    ).exists()
    return db.query(
        pairs.c.subject, pairs.c.knowledge_point,
        func.count(func.distinct(pairs.c.submission_id)).label("attempts"),
        func.count(func.distinct(case((has_error, pairs.c.submission_id)))).label("errors"),
        func.count(func.distinct(case((has_error, pairs.c.student_id)))).label("student_count"),
    ).group_by(pairs.c.subject, pairs.c.knowledge_point).all()


def week_start_for_database(now: datetime) -> datetime:
    # 业务时间按配置时区取本周一，转回与 Error.created_at 一致的本机 naive 时间。
    local_now = now.astimezone(ZoneInfo(settings.APP_TIMEZONE))
    start = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone().replace(tzinfo=None)


def same_teaching_day(first: datetime, second: datetime) -> bool:
    zone = ZoneInfo(settings.APP_TIMEZONE)
    return first.astimezone(zone).date() == second.astimezone(zone).date()


def build_teaching_plan(db: Session, teacher, *, now=None):
    now = now or datetime.now()
    stats = knowledge_point_stats(db, teacher)
    weak = [dict(subject=r.subject, knowledge_point=r.knowledge_point,
                 error_rate=round(r.errors / r.attempts, 3), student_count=r.student_count)
            for r in stats if r.student_count >= 2 and r.errors / r.attempts >= 0.5]
    weak.sort(key=lambda r: (-r["student_count"], -r["error_rate"], r["subject"], r["knowledge_point"]))
    records = db.query(TeacherTeachingFocus).filter(
        TeacherTeachingFocus.teacher_id == teacher.id,
    ).order_by(TeacherTeachingFocus.taught_at.desc(), TeacherTeachingFocus.subject,
               TeacherTeachingFocus.knowledge_point).all()
    taught = {(r.subject, r.knowledge_point): r.taught_at for r in records}
    topics = [{**r, "taught_at": taught.get((r["subject"], r["knowledge_point"]))} for r in weak[:3]]
    authorized_keys = {(r.subject, r.knowledge_point) for r in stats}
    latest = next((r for r in records if (r.subject, r.knowledge_point) in authorized_keys), None)
    follow_up = None
    if latest:
        since = max(latest.taught_at, week_start_for_database(now))
        students = scoped_attempts(db, teacher).join(Error, Error.submission_id == Submission.id).filter(
            Question.subject == latest.subject, Error.knowledge_point == latest.knowledge_point,
            # 提交和诊断都必须发生在讲解之后，防止迟到的旧作业批改算作复发。
            Submission.submitted_at > since, Error.created_at > since,
            Submission.submitted_at <= now, Error.created_at <= now,
        ).with_entities(func.count(func.distinct(Submission.student_id))).scalar()
        follow_up = dict(subject=latest.subject, knowledge_point=latest.knowledge_point,
                         taught_at=latest.taught_at, student_count=int(students or 0))
    return dict(topics=topics, follow_up=follow_up)


def source_question(db: Session, teacher, subject: str, knowledge_point: str):
    """动作只接受当前教师可见的学科知识点；不信任前端传来的题目正文。"""
    return scoped_attempts(db, teacher).join(Error, Error.submission_id == Submission.id).filter(
        Question.subject == subject, Error.knowledge_point == knowledge_point,
    ).with_entities(Question).order_by(Error.created_at.desc(), Error.id.desc()).first()
