"""从长期学习记忆的源记录派生关注名单，只统计教师授权范围，不读取跨班全局记忆。"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Correction, Error, Question, Submission, SubmissionReview, User, Verification


def students_needing_attention(
    db: Session, *, student_ids, assignment_ids, submission_ids, now=None,
) -> list[dict]:
    """每人保留最紧要的一条原因：反复出错、超过 7 天未订正、低修复率；最多 5 人。

    一次提交的多个错误步骤仅算一次出错。订正取最新记录；修复要求所有订正
    通过且最新变式验证通过、不早于最新错误。暂定待审核诊断不参加筛选。
    """
    if not student_ids or not assignment_ids:
        return []
    now = now or datetime.now()
    latest_correct = select(Correction.is_correct).where(
        Correction.error_id == Error.id,
        Correction.student_id == Submission.student_id,
    ).order_by(Correction.submitted_at.desc(), Correction.id.desc()).limit(1).correlate(
        Error, Submission,
    ).scalar_subquery()
    scoped = db.query(
        Error.id.label("error_id"), Submission.id.label("submission_id"),
        Submission.student_id.label("student_id"), Question.subject.label("subject"),
        Error.knowledge_point.label("knowledge_point"), Error.created_at.label("created_at"),
        case((latest_correct.is_(True), 1), else_=0).label("corrected"),
    ).join(Submission, Submission.id == Error.submission_id).join(
        Question, Question.id == Submission.question_id,
    ).outerjoin(SubmissionReview, SubmissionReview.submission_id == Submission.id).filter(
        Submission.student_id.in_(student_ids), Question.assignment_id.in_(assignment_ids),
        Submission.id.in_(submission_ids),
        (SubmissionReview.status.is_(None) | (SubmissionReview.status != "pending")),
    ).subquery()
    groups = db.query(
        scoped.c.student_id, scoped.c.subject, scoped.c.knowledge_point,
        func.count(func.distinct(scoped.c.submission_id)).label("mistakes"),
        func.count().label("errors"), func.sum(scoped.c.corrected).label("corrected"),
        func.min(case((scoped.c.corrected == 0, scoped.c.created_at))).label("unresolved_since"),
        func.max(scoped.c.created_at).label("last_error_at"),
    ).group_by(scoped.c.student_id, scoped.c.subject, scoped.c.knowledge_point).all()
    if not groups:
        return []

    ranked_verifications = db.query(
        scoped.c.student_id, scoped.c.subject, scoped.c.knowledge_point,
        Verification.status, Verification.completed_at,
        func.row_number().over(
            partition_by=(scoped.c.student_id, scoped.c.subject, scoped.c.knowledge_point),
            order_by=(Verification.created_at.desc(), Verification.id.desc()),
        ).label("rank"),
    ).join(Verification, Verification.source_error_id == scoped.c.error_id).filter(
        Verification.student_id == scoped.c.student_id,
        Verification.knowledge_point == scoped.c.knowledge_point,
        Verification.status.in_(("passed", "failed")),
    ).subquery()
    verifications = {
        (r.student_id, r.subject, r.knowledge_point): r
        for r in db.query(ranked_verifications).filter(ranked_verifications.c.rank == 1).all()
    }
    candidates = {}
    totals = defaultdict(lambda: [0, 0])

    def offer(student_id, priority, reason):
        if student_id not in candidates or priority < candidates[student_id][0]:
            candidates[student_id] = (priority, reason)

    for row in groups:
        verification = verifications.get((row.student_id, row.subject, row.knowledge_point))
        unresolved = row.errors - row.corrected
        fixed = bool(
            not unresolved and verification and verification.status == "passed"
            and verification.completed_at and verification.completed_at >= row.last_error_at
        )
        if row.knowledge_point.strip():
            totals[row.student_id][0] += 1
            totals[row.student_id][1] += int(fixed)
        if fixed:
            continue
        kp = row.knowledge_point.strip() or "未归类错题"
        days = max(0, (now - row.unresolved_since).days) if row.unresolved_since else 0
        if row.mistakes >= 3 and row.knowledge_point.strip():
            state = f"仍有{unresolved}处订正未通过" if unresolved else "尚未通过巩固验证"
            offer(row.student_id, (0, -row.mistakes, -days, row.subject, kp),
                  f"{kp}已错{row.mistakes}次，{state}")
        if days >= 7:
            offer(row.student_id, (1, -days, -unresolved, row.subject, kp),
                  f"{kp}已有{days}天未完成订正")

    # 至少 3 个知识点才比较修复率；仅提醒低于 50% 且处在同范围末四分位的学生。
    rates = sorted(fixed / total for total, fixed in totals.values() if total >= 3)
    if rates:
        cutoff = rates[(len(rates) - 1) // 4]
        for student_id, (total, fixed) in totals.items():
            rate = fixed / total
            if total >= 3 and rate < 0.5 and rate <= cutoff:
                offer(student_id, (2, rate, -total, "", ""),
                      f"{total}个出错知识点仅修复{fixed}个，修复率{rate:.0%}")

    selected = sorted(candidates, key=lambda sid: (candidates[sid][0], sid))[:5]
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_(selected), User.role == "student")}
    return [dict(id=sid, name=names[sid], reason=candidates[sid][1]) for sid in selected if sid in names]
