"""Shared evidence for the student profile, teacher portrait and teacher Agent."""
from collections import Counter, defaultdict

from sqlalchemy import and_, func, or_

from ..models import Correction, Error, Question, Step, Submission, SubmissionReview, Verification


_STATUS_ORDER = {
    "stubborn": 0, "pending": 1, "needs_review": 2, "awaiting_verify": 3,
    "fixed": 4, "corrected": 5, "clear": 6, "unclassified": 7,
}


def _unreadable(error) -> bool:
    return error.error_type == "无法解析" or (
        error.step_status == "unparseable" and not error.teacher_corrected
    )


def _summarize_point(row, errors) -> dict:
    confirmed = [error for error in errors if not _unreadable(error)]
    wrong_questions = {error.question_id for error in confirmed}
    questions_by_type = defaultdict(set)
    pending_by_type = defaultdict(set)
    for error in confirmed:
        questions_by_type[error.error_type].add(error.question_id)
        if not error.corrected:
            pending_by_type[error.error_type].add(error.question_id)
    patterns = [
        {
            "error_type": error_type,
            "question_count": len(questions),
            "pending_question_count": len(pending_by_type[error_type]),
        }
        for error_type, questions in questions_by_type.items()
    ]
    patterns.sort(key=lambda item: (
        -item["pending_question_count"], -item["question_count"], item["error_type"],
    ))

    pending = [error for error in errors if not error.corrected]
    review_count = sum(_unreadable(error) for error in pending)
    latest_error = errors[0] if errors else None
    if not row.knowledge_point:
        status = "unclassified"
    elif not latest_error:
        status = "clear"
    elif not pending:
        verified = any(
            error.verified_at is not None and error.verified_at >= latest_error.created_at
            and error.recorded_point == row.knowledge_point
            for error in errors
        )
        can_verify = row.subject == "math" and latest_error.recorded_point == row.knowledge_point
        status = "fixed" if verified else ("awaiting_verify" if can_verify else "corrected")
    elif patterns and patterns[0]["pending_question_count"] >= 2:
        status = "stubborn"
    else:
        status = "needs_review" if review_count == len(pending) else "pending"

    next_error = next((error for error in pending if not _unreadable(error)), None)
    if next_error is None:
        next_error = pending[0] if pending else latest_error
    return {
        "subject": row.subject,
        "knowledge_point": row.knowledge_point,
        "question_count": row.question_count,
        "attempts": row.attempts,
        "wrong_question_count": len(wrong_questions),
        "error_count": len(errors),
        "corrected_count": len(errors) - len(pending),
        "review_count": review_count,
        "patterns": patterns,
        "status": status,
        "next_error_id": next_error.id if next_error is not None else None,
    }


def student_knowledge_analysis(
    db, student_id: int, visible_only: bool = False, assignment_ids=None, submission_ids=None,
) -> tuple[dict, dict[int, dict]]:
    """Count graded questions once and keep evidence scoped to visible submissions."""
    has_error = db.query(Error.id).filter(Error.submission_id == Submission.id).exists()
    has_judged_step = db.query(Step.id).filter(
        Step.submission_id == Submission.id, Step.seq >= 1,
        Step.status.in_(("ok", "error", "unparseable")),
    ).exists()
    submissions = db.query(
        Submission.id.label("submission_id"), Question.id.label("question_id"),
        Question.subject, func.trim(Question.knowledge_point).label("knowledge_point"),
    ).select_from(Submission).join(Question, Question.id == Submission.question_id).filter(
        Submission.student_id == student_id,
        or_(Submission.status == "graded", and_(
            Submission.status == "submitted", or_(has_error, has_judged_step),
        )),
    )
    if assignment_ids is not None:
        submissions = submissions.filter(Question.assignment_id.in_(assignment_ids))
    if submission_ids is not None:
        submissions = submissions.filter(Submission.id.in_(submission_ids))
    if visible_only:
        pending_review = db.query(SubmissionReview.submission_id).filter(
            SubmissionReview.submission_id == Submission.id, SubmissionReview.status == "pending",
        ).exists()
        submissions = submissions.filter(~pending_review)
    scoped = submissions.cte("profile_submissions")

    question_counts = db.query(
        scoped.c.subject, scoped.c.knowledge_point,
        func.count(func.distinct(scoped.c.question_id)).label("question_count"),
        func.count(scoped.c.submission_id).label("attempts"),
    ).group_by(scoped.c.subject, scoped.c.knowledge_point).all()

    corrected = db.query(Correction.id).filter(
        Correction.error_id == Error.id, Correction.student_id == student_id,
        Correction.is_correct.is_(True),
    ).exists()
    verified_at = db.query(func.max(Verification.completed_at)).filter(
        Verification.student_id == student_id, Verification.source_error_id == Error.id,
        Verification.knowledge_point == Error.knowledge_point, Verification.status == "passed",
    ).correlate(Error).scalar_subquery()
    error_rows = db.query(
        Error.id, Error.error_type, Error.created_at, Error.teacher_corrected,
        func.trim(Error.knowledge_point).label("recorded_point"), Step.status.label("step_status"),
        scoped.c.question_id, scoped.c.subject, scoped.c.knowledge_point,
        corrected.label("corrected"), verified_at.label("verified_at"),
    ).select_from(Error).join(
        scoped, scoped.c.submission_id == Error.submission_id,
    ).outerjoin(Step, Step.id == Error.step_id).order_by(Error.created_at.desc(), Error.id.desc()).all()

    errors_by_point = defaultdict(list)
    record_metadata = {}
    error_types = Counter()
    for error in error_rows:
        errors_by_point[(error.subject, error.knowledge_point)].append(error)
        record_metadata[error.id] = {"subject": error.subject, "corrected": bool(error.corrected)}
        error_types["无法解析" if _unreadable(error) else error.error_type] += 1

    points = [
        _summarize_point(row, errors_by_point[(row.subject, row.knowledge_point)])
        for row in question_counts
    ]
    points.sort(key=lambda point: (
        _STATUS_ORDER[point["status"]],
        -point["wrong_question_count"],
        -(point["error_count"] - point["corrected_count"]),
        point["subject"], point["knowledge_point"],
    ))
    corrected_count = sum(point["corrected_count"] for point in points)
    return {
        "graded_question_count": sum(point["question_count"] for point in points),
        "wrong_question_count": sum(point["wrong_question_count"] for point in points),
        "corrected_count": corrected_count,
        "pending_correction_count": len(error_rows) - corrected_count,
        "points": points,
        "error_types": [
            {"error_type": name, "count": count}
            for name, count in sorted(error_types.items(), key=lambda item: (-item[1], item[0]))
        ],
    }, record_metadata
