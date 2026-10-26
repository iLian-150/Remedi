"""从错题、订正与变式验证构建可追溯的学生学科记忆。"""
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Correction, Error, Question, StudentLearningMemory, Submission,
    SubmissionReview, Verification,
)


def refresh_student_learning_memory(
    db: Session,
    student_id: int,
    *,
    subject: Optional[str] = None,
    knowledge_point: Optional[str] = None,
    commit: bool = True,
) -> int:
    """重算指定范围的记忆状态；待教师审核的暂定错因不进入长期记忆。"""
    db.info.pop(("student_learning_memory_checked", student_id), None)
    query = db.query(Error, Question.subject).join(
        Submission, Submission.id == Error.submission_id,
    ).join(
        Question, Question.id == Submission.question_id,
    ).outerjoin(
        SubmissionReview, SubmissionReview.submission_id == Submission.id,
    ).filter(
        Submission.student_id == student_id,
        (SubmissionReview.status.is_(None) | (SubmissionReview.status != "pending")),
    )
    if subject:
        query = query.filter(Question.subject == subject)
    if knowledge_point:
        query = query.filter(Error.knowledge_point == knowledge_point)
    error_rows = query.order_by(Error.created_at, Error.id).all()
    errors_by_key = defaultdict(list)
    for error, error_subject in error_rows:
        errors_by_key[(error_subject or "other", error.knowledge_point)].append(error)

    memory_query = db.query(StudentLearningMemory).filter(
        StudentLearningMemory.student_id == student_id,
    )
    if subject:
        memory_query = memory_query.filter(StudentLearningMemory.subject == subject)
    if knowledge_point:
        memory_query = memory_query.filter(StudentLearningMemory.knowledge_point == knowledge_point)
    existing = {
        (row.subject, row.knowledge_point): row for row in memory_query.all()
    }
    keys = set(errors_by_key) | set(existing)
    now = datetime.now()
    changed = 0
    for key in keys:
        error_list = errors_by_key.get(key, [])
        row = existing.get(key)
        if not error_list:
            if row is not None:
                db.delete(row)
                changed += 1
            continue

        error_ids = [error.id for error in error_list]
        correction_rows = db.query(Correction).filter(
            Correction.student_id == student_id,
            Correction.error_id.in_(error_ids),
        ).order_by(Correction.submitted_at, Correction.id).all()
        latest_correction = {}
        for correction in correction_rows:
            latest_correction[correction.error_id] = correction
        known_corrections = [
            item for item in latest_correction.values() if item.is_correct is not None
        ]
        successful = sum(1 for item in known_corrections if item.is_correct is True)
        corrected_count = successful
        correction_rate = successful / len(known_corrections) if known_corrections else 0.0

        verifications = db.query(Verification).filter(
            Verification.student_id == student_id,
            Verification.source_error_id.in_(error_ids),
            Verification.status.in_(("passed", "failed")),
        ).order_by(Verification.created_at, Verification.id).all()
        passed = sum(1 for item in verifications if item.status == "passed")
        verification_rate = passed / len(verifications) if verifications else 0.0
        latest_verification = verifications[-1].status if verifications else None
        if corrected_count == 0:
            state = "needs_practice"
        elif corrected_count < len(error_list):
            state = "correcting"
        elif latest_verification == "failed":
            state = "reinforcing"
        elif latest_verification == "passed" and verification_rate >= 0.8:
            state = "mastered"
        else:
            state = "correcting"

        label = {
            "needs_practice": "需要订正",
            "correcting": "订正中，建议继续验证",
            "reinforcing": "验证时仍有波动，需要加固",
            "mastered": "近期验证稳定通过",
        }[state]
        summary = (
            f"{key[0]} / {key[1]}：累计记录 {len(error_list)} 次错题；"
            f"最近订正确认正确 {corrected_count} 次；"
            f"变式验证通过率 {verification_rate:.0%}；当前状态：{label}。"
        )
        if row is None:
            row = StudentLearningMemory(
                student_id=student_id, subject=key[0], knowledge_point=key[1],
            )
            db.add(row)
            existing[key] = row
        row.error_count = len(error_list)
        row.corrected_count = corrected_count
        row.correction_success_rate = correction_rate
        row.verification_pass_rate = verification_rate
        row.state = state
        row.summary = summary
        row.updated_at = now
        changed += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return changed


def ensure_student_learning_memory(db: Session, student_id: int) -> None:
    """仅在派生记忆缺漏时重建，避免每次对话都扫描全部错题和逐点查询。"""
    cache_key = ("student_learning_memory_checked", student_id)
    if db.info.get(cache_key):
        return
    source_error_count = db.query(func.count(Error.id)).join(
        Submission, Submission.id == Error.submission_id,
    ).outerjoin(
        SubmissionReview, SubmissionReview.submission_id == Submission.id,
    ).filter(
        Submission.student_id == student_id,
        (SubmissionReview.status.is_(None) | (SubmissionReview.status != "pending")),
    ).scalar() or 0
    cached_error_count = db.query(
        func.coalesce(func.sum(StudentLearningMemory.error_count), 0),
    ).filter(
        StudentLearningMemory.student_id == student_id,
    ).scalar() or 0
    if source_error_count != cached_error_count:
        refresh_student_learning_memory(db, student_id, commit=True)
    db.info[cache_key] = True


def student_memory_to_text(db: Session, student_id: int, limit: int = 8) -> str:
    ensure_student_learning_memory(db, student_id)
    rows = db.query(StudentLearningMemory).filter(
        StudentLearningMemory.student_id == student_id,
    ).order_by(
        StudentLearningMemory.updated_at.desc(),
        StudentLearningMemory.error_count.desc(),
    ).limit(limit).all()
    if not rows:
        return "还没有足够的错题、订正和验证记录形成学习记忆。"
    return "本人学科学习记忆（从错题本、订正和变式验证汇总）：\n" + "\n".join(
        f"- {row.summary}" for row in rows
    )
