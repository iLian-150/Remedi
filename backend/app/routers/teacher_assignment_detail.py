"""教师查看已发布作业的完整题目。"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..api_schemas.base import QuestionGroupOut
from ..api_schemas.teacher import TeacherAssignmentOut, TeacherAssignmentQuestionOut
from ..auth import require_teacher
from ..database import get_db
from ..models import Assignment, DiagramJob, QuestionGroup, QuestionGroupMember, User
from .teacher import (
    _scoped_teacher_assignment_class_pairs,
    _scoped_teacher_assignment_question_ids,
    _scoped_teacher_essay_ids,
    _teacher_assignment_ids,
    _teacher_assignments_out,
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
