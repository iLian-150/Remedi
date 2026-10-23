"""按学生、学科与知识点查找可回看的历史错题。"""
from typing import Iterable

from sqlalchemy import and_, func, select, union_all
from sqlalchemy.orm import Session, load_only

from ..models import (
    Assignment,
    Correction,
    Error,
    Question,
    Step,
    StudentMistakeArchive,
    Submission,
    SubmissionReview,
)
from .answer_check import student_visible_solution_steps
from . import reviews as review_svc

_KNOWLEDGE_POINT_WHITESPACE = (
    " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def _knowledge_point_key_expression():
    value = Error.knowledge_point
    for character in _KNOWLEDGE_POINT_WHITESPACE:
        value = func.replace(value, character, "")
    return func.lower(value)


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
    query = query.filter(_knowledge_point_key_expression() == knowledge_key)

    for error, submission, question, assignment, step in query.limit(1):
        latest_correction_id = (
            db.query(Correction.id)
            .filter(Correction.student_id == student_id, Correction.error_id == error.id)
            .order_by(Correction.submitted_at.desc(), Correction.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        review_and_correction = (
            db.query(
                SubmissionReview.status.label("review_status"),
                Correction.id.label("correction_id"),
                Correction.content.label("correction_content"),
                Correction.is_correct.label("correction_is_correct"),
                Correction.note.label("correction_note"),
                Correction.submitted_at.label("correction_submitted_at"),
            )
            .select_from(Submission)
            .outerjoin(
                SubmissionReview,
                SubmissionReview.submission_id == Submission.id,
            )
            .outerjoin(Correction, Correction.id == latest_correction_id)
            .filter(
                Submission.id == submission.id,
                Submission.student_id == student_id,
            )
            .first()
        )
        review_status = review_and_correction.review_status
        correction = (
            {
                "id": review_and_correction.correction_id,
                "content": review_and_correction.correction_content,
                "is_correct": review_and_correction.correction_is_correct,
                "note": review_and_correction.correction_note,
                "submitted_at": review_and_correction.correction_submitted_at,
            }
            if review_and_correction.correction_id is not None else None
        )
        return {
            "id": error.id,
            "submission_id": submission.id,
            "review_status": (
                review_status if review_status is not None else review_svc.APPROVED
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
            "latest_correction": correction,
        }
    return None


def find_related_mistakes_for_questions(
    db: Session,
    student_id: int,
    questions: Iterable[Question],
    *,
    exclude_assignment_id: int | None = None,
) -> dict[int, dict | None]:
    """Batch the same latest unarchived history lookup for all questions in an assignment."""
    questions = list(questions)
    normalized_subjects = {
        "数学": "math",
        "english": "english",
        "英语": "english",
        "英语作文": "english",
    }
    question_keys = {}
    knowledge_keys_by_subject = {}
    for question in questions:
        subject_key = (question.subject or "").strip().casefold()
        subject_key = normalized_subjects.get(subject_key, subject_key)
        knowledge_key = "".join((question.knowledge_point or "").split()).casefold()
        if not subject_key or not knowledge_key:
            continue
        question_keys[question.id] = (subject_key, knowledge_key)
        knowledge_keys_by_subject.setdefault(subject_key, set()).add(knowledge_key)

    result = {question.id: None for question in questions}
    if not knowledge_keys_by_subject:
        return result

    candidate_columns = (
        "error_id",
        "knowledge_point",
        "error_type",
        "detail",
        "created_at",
        "submission_id",
        "question_id",
        "question_subject",
        "question_stem",
        "assignment_id",
        "assignment_title",
        "assignment_created_at",
        "step_seq",
        "step_text",
    )
    candidate_selects = []
    for subject_key in knowledge_keys_by_subject:
        query = (
            db.query(
                Error.id.label("error_id"),
                Error.knowledge_point.label("knowledge_point"),
                Error.error_type.label("error_type"),
                Error.detail.label("detail"),
                Error.created_at.label("created_at"),
                Submission.id.label("submission_id"),
                Question.id.label("question_id"),
                Question.subject.label("question_subject"),
                Question.stem.label("question_stem"),
                Assignment.id.label("assignment_id"),
                Assignment.title.label("assignment_title"),
                Assignment.created_at.label("assignment_created_at"),
                Step.seq.label("step_seq"),
                Step.text.label("step_text"),
            )
            .join(Submission, Error.submission_id == Submission.id)
            .join(Question, Submission.question_id == Question.id)
            .join(Assignment, Question.assignment_id == Assignment.id)
            .outerjoin(Step, Error.step_id == Step.id)
            .filter(
                Submission.student_id == student_id,
                Question.subject == subject_key,
            )
        )
        if exclude_assignment_id is not None:
            query = query.filter(Assignment.id != exclude_assignment_id)

        is_archived = db.query(StudentMistakeArchive.error_id).filter(
            StudentMistakeArchive.student_id == student_id,
            StudentMistakeArchive.error_id == Error.id,
        ).exists()
        knowledge_point_key = _knowledge_point_key_expression()
        candidate_subquery = (
            query.filter(
                ~is_archived,
                knowledge_point_key.in_(knowledge_keys_by_subject[subject_key]),
            ).add_columns(
                func.row_number().over(
                    partition_by=knowledge_point_key,
                    order_by=(Error.created_at.desc(), Error.id.desc()),
                ).label("knowledge_point_rank")
            )
            .subquery()
        )
        candidate_selects.append(
            select(*(candidate_subquery.c[column] for column in candidate_columns))
            .where(candidate_subquery.c.knowledge_point_rank == 1)
        )

    candidate_union = union_all(*candidate_selects).subquery()
    candidate_rows = db.execute(
        select(candidate_union).order_by(
            candidate_union.c.created_at.desc(),
            candidate_union.c.error_id.desc(),
        )
    ).all()
    candidate_by_key = {}
    for row in candidate_rows:
        subject_key = (row.question_subject or "").strip().casefold()
        subject_key = normalized_subjects.get(subject_key, subject_key)
        knowledge_key = "".join((row.knowledge_point or "").split()).casefold()
        key = (subject_key, knowledge_key)
        if (
            knowledge_key in knowledge_keys_by_subject.get(subject_key, set())
            and key not in candidate_by_key
        ):
            candidate_by_key[key] = row

    error_ids = list(dict.fromkeys(
        row.error_id for row in candidate_by_key.values()
    ))
    correction_by_error = {}
    for start in range(0, len(error_ids), 500):
        error_id_chunk = error_ids[start:start + 500]
        ranked_corrections = db.query(
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
        ).filter(
            Correction.student_id == student_id,
            Correction.error_id.in_(error_id_chunk),
        ).subquery()
        latest = ranked_corrections.c
        correction_by_error.update({
            error_id: {
                "id": correction_id,
                "content": content,
                "is_correct": is_correct,
                "note": note,
                "submitted_at": submitted_at,
            }
            for error_id, correction_id, content, is_correct, note, submitted_at
            in db.query(
                latest.error_id,
                latest.id,
                latest.content,
                latest.is_correct,
                latest.note,
                latest.submitted_at,
            ).filter(latest.rank == 1).all()
        })

    review_by_submission = review_svc.review_status_map(
        db, {row.submission_id for row in candidate_by_key.values()}
    )
    payload_by_error = {}
    payload_by_key = {}
    for key, row in candidate_by_key.items():
        payload = payload_by_error.get(row.error_id)
        if payload is None:
            payload = {
                "id": row.error_id,
                "submission_id": row.submission_id,
                "review_status": review_by_submission.get(
                    row.submission_id, review_svc.APPROVED
                ),
                "question_id": row.question_id,
                "assignment_id": row.assignment_id,
                "assignment_title": row.assignment_title,
                "assignment_created_at": row.assignment_created_at,
                "question_subject": row.question_subject,
                "question_stem": row.question_stem,
                "solution_steps": student_visible_solution_steps(row.question_stem)
                if row.question_subject == "math" else [],
                "knowledge_point": row.knowledge_point,
                "error_type": row.error_type,
                "detail": row.detail,
                "step_seq": row.step_seq,
                "step_text": row.step_text,
                "created_at": row.created_at,
                "latest_correction": correction_by_error.get(row.error_id),
            }
            payload_by_error[row.error_id] = payload
        payload_by_key[key] = payload

    for question_id, key in question_keys.items():
        result[question_id] = payload_by_key.get(key)
    return result


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
        is_archived = db.query(StudentMistakeArchive.error_id).filter(
            StudentMistakeArchive.student_id == student_id,
            StudentMistakeArchive.error_id == Error.id,
        ).exists()
        valid_error_ids = (
            db.query(Error.id.label("error_id"))
            .join(Submission, Error.submission_id == Submission.id)
            .filter(
                Error.id.in_(batch_ids),
                Submission.student_id == student_id,
                ~is_archived,
            )
            .cte("valid_related_error_ids")
        )
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
            .join(
                valid_error_ids,
                valid_error_ids.c.error_id == Correction.error_id,
            )
            .filter(Correction.student_id == student_id)
            .subquery()
        )
        latest = ranked_corrections.c
        rows = (
            db.query(
                Error,
                Submission,
                Question,
                Assignment,
                Step,
                SubmissionReview.status.label("review_status"),
                latest.id.label("correction_id"),
                latest.content.label("correction_content"),
                latest.is_correct.label("correction_is_correct"),
                latest.note.label("correction_note"),
                latest.submitted_at.label("correction_submitted_at"),
            )
            .join(valid_error_ids, valid_error_ids.c.error_id == Error.id)
            .join(Submission, Error.submission_id == Submission.id)
            .join(Question, Submission.question_id == Question.id)
            .join(Assignment, Question.assignment_id == Assignment.id)
            .outerjoin(Step, Error.step_id == Step.id)
            .outerjoin(
                SubmissionReview,
                SubmissionReview.submission_id == Submission.id,
            )
            .outerjoin(
                ranked_corrections,
                and_(
                    latest.error_id == Error.id,
                    latest.rank == 1,
                ),
            )
            .filter(Submission.student_id == student_id)
            .all()
        )

        for (
            error,
            submission,
            question,
            assignment,
            step,
            review_status,
            correction_id,
            correction_content,
            correction_is_correct,
            correction_note,
            correction_submitted_at,
        ) in rows:
            result[error.id] = {
                "id": error.id,
                "submission_id": submission.id,
                "review_status": (
                    review_status
                    if review_status is not None else review_svc.APPROVED
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
                "latest_correction": ({
                    "id": correction_id,
                    "content": correction_content,
                    "is_correct": correction_is_correct,
                    "note": correction_note,
                    "submitted_at": correction_submitted_at,
                } if correction_id is not None else None),
            }
    return result
