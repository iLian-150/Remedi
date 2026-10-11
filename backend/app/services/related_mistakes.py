"""按学生、学科与知识点查找可回看的历史错题。"""
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    Correction,
    Error,
    Question,
    Step,
    StudentMistakeArchive,
    Submission,
)
from .answer_check import student_visible_solution_steps
from . import reviews as review_svc


def find_related_mistake(db: Session, student_id: int, subject: str,
                         knowledge_point: str, *, exclude_assignment_id: int | None = None) -> dict | None:
    """返回该学生最近一条已审核、未归档的同学科同知识点错题。"""
    subject_key = (subject or "").strip().casefold()
    subject_key = {
        "数学": "math",
        "english": "english",
        "英语": "english",
        "英语作文": "english",
    }.get(subject_key, subject_key)
    knowledge_key = "".join((knowledge_point or "").split()).casefold()
    if not subject_key or not knowledge_key:
        return None

    query = (
        db.query(Error, Submission, Question, Assignment, Step)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .join(Assignment, Question.assignment_id == Assignment.id)
        .outerjoin(Step, Error.step_id == Step.id)
        .filter(Submission.student_id == student_id, Question.subject == subject_key)
        .order_by(Error.created_at.desc(), Error.id.desc())
    )
    if exclude_assignment_id is not None:
        query = query.filter(Assignment.id != exclude_assignment_id)

    pending_ids = review_svc.pending_submission_ids(db, student_id)
    archived_ids = {
        row[0]
        for row in db.query(StudentMistakeArchive.error_id)
        .filter(StudentMistakeArchive.student_id == student_id)
        .all()
    }

    for error, submission, question, assignment, step in query.limit(300).all():
        if submission.id in pending_ids or error.id in archived_ids:
            continue
        if "".join((error.knowledge_point or "").split()).casefold() != knowledge_key:
            continue
        correction = (
            db.query(Correction)
            .filter(Correction.student_id == student_id, Correction.error_id == error.id)
            .order_by(Correction.submitted_at.desc(), Correction.id.desc())
            .first()
        )
        return {
            "id": error.id,
            "submission_id": submission.id,
            "question_id": question.id,
            "assignment_id": assignment.id,
            "assignment_title": assignment.title,
            "assignment_created_at": assignment.created_at,
            "question_subject": question.subject,
            "question_stem": question.stem,
            "solution_steps": student_visible_solution_steps(question.stem)
            if question.subject == "math" else [],
            "knowledge_point": error.knowledge_point,
            "error_type": error.error_type,
            "detail": error.detail,
            "step_seq": step.seq if step else None,
            "step_text": step.text if step else None,
            "created_at": error.created_at,
            "latest_correction": ({
                "id": correction.id,
                "content": correction.content,
                "is_correct": correction.is_correct,
                "note": correction.note,
                "submitted_at": correction.submitted_at,
            } if correction else None),
        }
    return None


def find_related_mistake_for_error(db: Session, student_id: int, error_id: int) -> dict | None:
    """加载已关联错题并再次校验归属与审核状态。"""
    row = (
        db.query(Error, Submission, Question, Assignment, Step)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .join(Assignment, Question.assignment_id == Assignment.id)
        .outerjoin(Step, Error.step_id == Step.id)
        .filter(Error.id == error_id, Submission.student_id == student_id)
        .first()
    )
    if row is None:
        return None
    error, submission, question, assignment, step = row
    archived = db.query(StudentMistakeArchive.id).filter_by(
        student_id=student_id, error_id=error.id
    ).first()
    if archived or not review_svc.is_visible_to_student(db, submission.id):
        return None
    correction = (
        db.query(Correction)
        .filter(Correction.student_id == student_id, Correction.error_id == error.id)
        .order_by(Correction.submitted_at.desc(), Correction.id.desc())
        .first()
    )
    return {
        "id": error.id,
        "submission_id": submission.id,
        "question_id": question.id,
        "assignment_id": assignment.id,
        "assignment_title": assignment.title,
        "assignment_created_at": assignment.created_at,
        "question_subject": question.subject,
        "question_stem": question.stem,
        "solution_steps": student_visible_solution_steps(question.stem)
        if question.subject == "math" else [],
        "knowledge_point": error.knowledge_point,
        "error_type": error.error_type,
        "detail": error.detail,
        "step_seq": step.seq if step else None,
        "step_text": step.text if step else None,
        "created_at": error.created_at,
        "latest_correction": ({
            "id": correction.id,
            "content": correction.content,
            "is_correct": correction.is_correct,
            "note": correction.note,
            "submitted_at": correction.submitted_at,
        } if correction else None),
    }
