"""按学生、学科与知识点查找可回看的历史错题。"""
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

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
    """返回该学生最近一条未归档的同学科同知识点错题（含待教师复核记录）。"""
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
        .options(
            load_only(
                Error.id, Error.knowledge_point, Error.error_type,
                Error.detail, Error.created_at,
            ),
            load_only(Submission.id),
            load_only(Question.id, Question.subject, Question.stem),
            load_only(Assignment.id, Assignment.title, Assignment.created_at),
            load_only(Step.id, Step.seq, Step.text),
        )
        .filter(Submission.student_id == student_id, Question.subject == subject_key)
        .order_by(Error.created_at.desc(), Error.id.desc())
    )
    if exclude_assignment_id is not None:
        query = query.filter(Assignment.id != exclude_assignment_id)

    is_archived = db.query(StudentMistakeArchive.error_id).filter(
        StudentMistakeArchive.student_id == student_id,
        StudentMistakeArchive.error_id == Error.id,
    ).exists()
    query = query.filter(~is_archived)

    for error, submission, question, assignment, step in query.limit(300).all():
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
            "review_status": review_svc.review_status(db, submission.id),
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
    return find_related_mistakes_for_errors(db, student_id, [error_id]).get(error_id)


def find_related_mistakes_for_errors(
    db: Session, student_id: int, error_ids: Iterable[int]
) -> dict[int, dict | None]:
    """批量加载关联错题详情，并分批处理以适配 SQLite 参数限制。"""
    unique_ids = list(
        dict.fromkeys(error_id for error_id in error_ids if error_id is not None)
    )
    result = {error_id: None for error_id in unique_ids}

    for start in range(0, len(unique_ids), 500):
        batch_ids = unique_ids[start:start + 500]
        rows = (
            db.query(Error, Submission, Question, Assignment, Step)
            .join(Submission, Error.submission_id == Submission.id)
            .join(Question, Submission.question_id == Question.id)
            .join(Assignment, Question.assignment_id == Assignment.id)
            .outerjoin(Step, Error.step_id == Step.id)
            .filter(Error.id.in_(batch_ids), Submission.student_id == student_id)
            .all()
        )
        if not rows:
            continue

        archived_ids = {
            error_id
            for (error_id,) in db.query(StudentMistakeArchive.error_id).filter(
                StudentMistakeArchive.student_id == student_id,
                StudentMistakeArchive.error_id.in_(batch_ids),
            ).all()
        }
        valid_rows = [
            row for row in rows if row[0].id not in archived_ids
        ]
        if not valid_rows:
            continue
        valid_error_ids = {error.id for error, _, _, _, _ in valid_rows}
        ranked_corrections = (
            db.query(
                Correction.error_id.label("error_id"),
                Correction.id.label("id"),
                Correction.content.label("content"),
                Correction.is_correct.label("is_correct"),
                Correction.note.label("note"),
                Correction.submitted_at.label("submitted_at"),
                func.row_number().over(
                    partition_by=Correction.error_id,
                    order_by=(Correction.submitted_at.desc(), Correction.id.desc()),
                ).label("rank"),
            )
            .filter(
                Correction.student_id == student_id,
                Correction.error_id.in_(valid_error_ids),
            )
            .subquery()
        )
        latest = ranked_corrections.c
        correction_by_error = {
            correction.error_id: {
                "id": correction.id,
                "content": correction.content,
                "is_correct": correction.is_correct,
                "note": correction.note,
                "submitted_at": correction.submitted_at,
            }
            for correction in db.query(
                latest.error_id,
                latest.id,
                latest.content,
                latest.is_correct,
                latest.note,
                latest.submitted_at,
            ).filter(latest.rank == 1).all()
        }
        review_by_submission = review_svc.review_status_map(
            db, {submission.id for _, submission, _, _, _ in valid_rows}
        )

        for error, submission, question, assignment, step in valid_rows:
            result[error.id] = {
                "id": error.id,
                "submission_id": submission.id,
                "review_status": review_by_submission.get(
                    submission.id, review_svc.APPROVED
                ),
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
                "latest_correction": correction_by_error.get(error.id),
            }
    return result
