"""教师查看已发布作业的完整题目。"""
import json
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..api_schemas.base import QuestionGroupOut
from ..api_schemas.teacher import TeacherAssignmentOut, TeacherAssignmentQuestionOut
from ..auth import require_teacher
from ..database import get_db
from ..models import (
    Assignment,
    AssignmentScoring,
    DiagramJob,
    Essay,
    Question,
    QuestionGroup,
    QuestionGroupMember,
    QuestionWeight,
    Step,
    Submission,
    SubmissionReview,
    SubmissionScore,
    User,
)
from ..services.teacher_scope import teacher_assignment_question_student_pairs
from .teacher import (
    _scoped_teacher_assignment_class_pairs,
    _scoped_teacher_assignment_question_ids,
    _scoped_teacher_essay_ids,
    _teacher_assignment_ids,
    _teacher_assignments_out,
    _scoped_teacher_student_ids,
    _teacher_submission_ids,
)

router = APIRouter(prefix="/api/teacher/assignments", tags=["teacher"])


class TeacherDetailQuestion(TeacherAssignmentQuestionOut):
    group_id: Optional[int] = None


class TeacherAssignmentDetail(TeacherAssignmentOut):
    questions: List[TeacherDetailQuestion]
    groups: List[QuestionGroupOut] = []


@router.get("/{assignment_id}", response_model=TeacherAssignmentDetail, summary="教师查看作业题目")
def assignment_detail(assignment_id: int, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.id.in_(_teacher_assignment_ids(db, current)),
    ).first()
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在或你没有该学科的查看权限。")
    ids = [assignment_id]
    visible_pairs = set(_scoped_teacher_assignment_class_pairs(db, current, ids).all())
    item = _teacher_assignments_out(
        [assignment], db, current,
        submission_ids=_teacher_submission_ids(db, current),
        essay_ids=_scoped_teacher_essay_ids(db, current),
        question_ids=_scoped_teacher_assignment_question_ids(db, current, ids),
        visible_class_pairs=visible_pairs,
    )[0]
    visible_question_ids = [question.id for question in item.questions]
    memberships = dict(db.query(QuestionGroupMember.question_id, QuestionGroupMember.group_id).filter(
        QuestionGroupMember.question_id.in_(visible_question_ids),
    ).all())
    group_ids = set(memberships.values())
    groups = db.query(QuestionGroup).filter(
        QuestionGroup.assignment_id == assignment_id, QuestionGroup.id.in_(group_ids),
    ).order_by(QuestionGroup.order_num, QuestionGroup.id).all()
    statuses = dict(db.query(DiagramJob.group_id, DiagramJob.status).filter(
        DiagramJob.group_id.in_(group_ids),
    ).all())
    return {
        **item.model_dump(),
        "questions": [{**q.model_dump(), "group_id": memberships.get(q.id)} for q in item.questions],
        "groups": [{"id": g.id, "stem": g.stem, "order_num": g.order_num,
                    "diagram": json.loads(g.diagram_json) if g.diagram_json else None,
                    "diagram_status": statuses.get(g.id)} for g in groups],
    }


@router.get("/{assignment_id}/analytics", summary="教师查看作业学情")
def assignment_analytics(
    assignment_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.id.in_(_teacher_assignment_ids(db, current)),
    ).first()
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在或你没有该学科的查看权限。")

    visible_question_ids = {
        row[0] for row in _scoped_teacher_assignment_question_ids(
            db, current, [assignment_id],
        ).all()
    }
    questions = db.query(Question).filter(
        Question.assignment_id == assignment_id,
        Question.id.in_(visible_question_ids),
    ).order_by(Question.order_num, Question.id).all()
    question_ids = [question.id for question in questions]
    if not question_ids:
        return _empty_assignment_analytics(assignment)

    scoped_pairs_query = teacher_assignment_question_student_pairs(
        db, current, assignment_id,
    )
    if scoped_pairs_query is None:
        student_ids = sorted({row[0] for row in _scoped_teacher_student_ids(db, current).all()})
        expected_pairs = {
            (student_id, question_id)
            for student_id in student_ids
            for question_id in question_ids
        }
    else:
        expected_pairs = {
            (student_id, question_id)
            for student_id, question_id in scoped_pairs_query.all()
            if question_id in visible_question_ids
        }
        student_ids = sorted({student_id for student_id, _ in expected_pairs})

    students_by_id = {}
    for start in range(0, len(student_ids), 400):
        rows = db.query(User).filter(User.id.in_(student_ids[start:start + 400])).all()
        students_by_id.update({student.id: student for student in rows})
    expected_pairs = {
        pair for pair in expected_pairs if pair[0] in students_by_id
    }
    student_ids = sorted(students_by_id)

    expected_by_question = defaultdict(set)
    expected_by_student = defaultdict(set)
    for student_id, question_id in expected_pairs:
        expected_by_question[question_id].add(student_id)
        expected_by_student[student_id].add(question_id)

    submissions_by_pair = {}
    essays_by_pair = {}
    if student_ids:
        allowed_submission_ids = _teacher_submission_ids(db, current)
        allowed_essay_ids = _scoped_teacher_essay_ids(db, current)
        for start in range(0, len(student_ids), 400):
            student_chunk = student_ids[start:start + 400]
            submission_rows = db.query(Submission).filter(
                Submission.question_id.in_(question_ids),
                Submission.student_id.in_(student_chunk),
                Submission.id.in_(allowed_submission_ids),
            ).order_by(Submission.submitted_at.desc(), Submission.id.desc()).all()
            for submission in submission_rows:
                pair = (submission.student_id, submission.question_id)
                if pair in expected_pairs and pair not in submissions_by_pair:
                    submissions_by_pair[pair] = submission

            essay_rows = db.query(Essay).filter(
                Essay.question_id.in_(question_ids),
                Essay.student_id.in_(student_chunk),
                Essay.id.in_(allowed_essay_ids),
                Essay.status != "superseded",
            ).order_by(Essay.submitted_at.desc(), Essay.id.desc()).all()
            for essay in essay_rows:
                pair = (essay.student_id, essay.question_id)
                if pair in expected_pairs and pair not in essays_by_pair:
                    essays_by_pair[pair] = essay

    question_by_id = {question.id: question for question in questions}
    assignment_total_row = db.query(AssignmentScoring.total_score).filter(
        AssignmentScoring.assignment_id == assignment_id,
    ).first()
    assignment_total = float(assignment_total_row[0]) if assignment_total_row and assignment_total_row[0] else 100.0
    question_count = db.query(func.count(Question.id)).filter(
        Question.assignment_id == assignment_id,
    ).scalar() or 0
    weights = dict(db.query(
        QuestionWeight.question_id, QuestionWeight.weight_pct,
    ).filter(
        QuestionWeight.question_id.in_(question_ids),
    ).all())
    default_weight = 100.0 / question_count if question_count else 100.0
    max_scores = {
        question.id: (
            round(assignment_total * float(weights.get(question.id, default_weight)) / 100.0, 1)
            if question.subject == "math" else 100.0
        )
        for question in questions
    }

    graded_submission_ids = [
        submission.id for submission in submissions_by_pair.values()
        if submission.status == "graded"
    ]
    score_rows = {}
    if graded_submission_ids:
        score_rows = {
            row.submission_id: row
            for start in range(0, len(graded_submission_ids), 400)
            for row in db.query(SubmissionScore).filter(
                SubmissionScore.submission_id.in_(graded_submission_ids[start:start + 400])
            ).all()
        }
    needs_step_score_ids = [
        submission_id for submission_id in graded_submission_ids
        if submission_id not in score_rows
    ]
    step_counts = {}
    for start in range(0, len(needs_step_score_ids), 400):
        rows = db.query(
            Step.submission_id,
            func.sum(case((Step.status == "ok", 1), else_=0)),
            func.count(Step.id),
        ).filter(
            Step.submission_id.in_(needs_step_score_ids[start:start + 400]),
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).group_by(Step.submission_id).all()
        step_counts.update({
            submission_id: (int(correct or 0), int(total or 0))
            for submission_id, correct, total in rows
        })

    pending_review_ids = set()
    if graded_submission_ids:
        pending_review_ids = {
            row[0] for row in db.query(SubmissionReview.submission_id).filter(
                SubmissionReview.submission_id.in_(graded_submission_ids),
                SubmissionReview.status == "pending",
            ).all()
        }

    submitted_pairs = set()
    pending_pairs = set()
    scored_pairs = set()
    review_pairs = set()
    score_by_pair = {}
    for pair, submission in submissions_by_pair.items():
        question = question_by_id[pair[1]]
        if question.subject != "math":
            continue
        submitted_pairs.add(pair)
        if submission.status != "graded":
            pending_pairs.add(pair)
            continue
        max_score = max_scores[question.id]
        saved_score = score_rows.get(submission.id)
        if saved_score is not None:
            earned = saved_score.final_score
            if earned is None:
                earned = saved_score.ai_score
        else:
            correct, total = step_counts.get(submission.id, (0, 0))
            earned = round(max_score * (correct / total if total else 0.0), 1)
        earned = max(0.0, min(max_score, float(earned))) if max_score else 0.0
        score_by_pair[pair] = (earned, max_score, submission.id in pending_review_ids)
        scored_pairs.add(pair)
        if submission.id in pending_review_ids:
            review_pairs.add(pair)

    for pair, essay in essays_by_pair.items():
        question = question_by_id[pair[1]]
        if question.subject == "math":
            continue
        submitted_pairs.add(pair)
        total_score = None
        if essay.status == "submitted":
            try:
                value = json.loads(essay.scores_json or "{}").get("total")
                if isinstance(value, (int, float)):
                    total_score = max(0.0, min(100.0, float(value)))
            except (TypeError, ValueError, json.JSONDecodeError):
                total_score = None
        if total_score is None:
            pending_pairs.add(pair)
            continue
        score_by_pair[pair] = (total_score, 100.0, False)
        scored_pairs.add(pair)

    score_totals_by_question = defaultdict(lambda: [0.0, 0])
    for (_student_id, question_id), (earned, max_score, _pending_review) in score_by_pair.items():
        rate = earned / max_score if max_score else 0.0
        score_totals_by_question[question_id][0] += rate
        score_totals_by_question[question_id][1] += 1

    question_items = []
    for index, question in enumerate(questions, start=1):
        expected_count = len(expected_by_question[question.id])
        submitted_count = sum(
            (student_id, question.id) in submitted_pairs
            for student_id in expected_by_question[question.id]
        )
        graded_count = sum(
            (student_id, question.id) in scored_pairs
            for student_id in expected_by_question[question.id]
        )
        rate_total, rate_count = score_totals_by_question[question.id]
        question_items.append({
            "id": question.id,
            "number": index,
            "subject": question.subject,
            "prompt": question.stem,
            "knowledge_point": question.knowledge_point,
            "expected_students": expected_count,
            "submitted_students": submitted_count,
            "graded_students": graded_count,
            "average_score_rate": round(rate_total / rate_count, 4) if rate_count else None,
        })

    student_items = []
    progress_counts = defaultdict(int)
    for student_id in student_ids:
        expected_questions = expected_by_student[student_id]
        student_submitted = {
            question_id for question_id in expected_questions
            if (student_id, question_id) in submitted_pairs
        }
        student_scored = {
            question_id for question_id in expected_questions
            if (student_id, question_id) in scored_pairs
        }
        pending_count = sum(
            (student_id, question_id) in pending_pairs
            for question_id in expected_questions
        )
        if not student_submitted:
            progress = "未开始"
        elif len(student_submitted) < len(expected_questions):
            progress = "部分提交"
        elif pending_count:
            progress = "批改中"
        elif any((student_id, question_id) in review_pairs for question_id in expected_questions):
            progress = "待复核"
        else:
            progress = "已完成"
        progress_counts[progress] += 1

        earned_total = sum(
            score_by_pair[(student_id, question_id)][0]
            for question_id in student_scored
        )
        max_total = sum(
            score_by_pair[(student_id, question_id)][1]
            for question_id in student_scored
        )
        student = students_by_id[student_id]
        student_items.append({
            "id": student.id,
            "name": student.name,
            "student_no": student.student_no,
            "expected_questions": len(expected_questions),
            "submitted_questions": len(student_submitted),
            "graded_questions": len(student_scored),
            "score": round(earned_total, 1),
            "max_score": round(max_total, 1),
            "score_rate": round(earned_total / max_total, 4) if max_total else None,
            "status": progress,
        })
    student_items.sort(key=lambda item: (item["name"], item["id"]))

    return {
        "assignment_id": assignment.id,
        "title": assignment.title,
        "student_count": len(student_items),
        "started_count": sum(item["submitted_questions"] > 0 for item in student_items),
        "completed_count": progress_counts["已完成"] + progress_counts["批改中"] + progress_counts["待复核"],
        "grading_count": len(pending_pairs),
        "review_count": len(review_pairs),
        "question_count": len(questions),
        "progress_counts": dict(progress_counts),
        "questions": question_items,
        "students": student_items,
    }


def _empty_assignment_analytics(assignment: Assignment):
    return {
        "assignment_id": assignment.id,
        "title": assignment.title,
        "student_count": 0,
        "started_count": 0,
        "completed_count": 0,
        "grading_count": 0,
        "review_count": 0,
        "question_count": 0,
        "progress_counts": {},
        "questions": [],
        "students": [],
    }
