"""明日讲评的读取、变式生成和显式已讲记录。"""
from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_teacher
from ..database import get_db
from ..models import TeacherTeachingFocus, User
from ..services.teaching_plan import build_teaching_plan, same_teaching_day, source_question
from ..services.variant_gen import generate_teaching_variant

router = APIRouter(prefix="/api/teacher/teaching-plan", tags=["teacher"])
logger = logging.getLogger(__name__)


class TopicIn(BaseModel):
    subject: str = Field(min_length=1, max_length=32)
    knowledge_point: str = Field(min_length=1, max_length=64)


class TopicOut(TopicIn):
    error_rate: float
    student_count: int
    taught_at: Optional[datetime] = None


class FollowUpOut(TopicIn):
    taught_at: datetime
    student_count: int


class TeachingPlanOut(BaseModel):
    topics: list[TopicOut] = Field(max_length=3)
    follow_up: Optional[FollowUpOut] = None


class ExerciseOut(TopicIn):
    prompt: str = Field(min_length=1, max_length=12000)
    standard_steps: list[str] = Field(min_length=1, max_length=30)
    answer: str = Field(min_length=1, max_length=12000)


def require_topic(db, teacher, topic):
    question = source_question(db, teacher, topic.subject, topic.knowledge_point)
    if question is None:
        raise HTTPException(404, "未找到可查看的知识点。")
    return question


@router.get("", response_model=TeachingPlanOut)
def teaching_plan(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    return build_teaching_plan(db, current)


@router.post("/exercise", response_model=ExerciseOut)
def exercise(body: TopicIn, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    question = require_topic(db, current, body)
    try:
        result = generate_teaching_variant(body.subject, body.knowledge_point, question.stem)
        return ExerciseOut(**body.model_dump(), **result)
    except Exception as exc:
        logger.warning("教师变式练习生成失败（%s）", type(exc).__name__)
        raise HTTPException(503, "变式练习暂时生成失败，请重试。") from None


@router.post("/taught", response_model=TeachingPlanOut)
def mark_taught(body: TopicIn, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    require_topic(db, current, body)
    key = (current.id, body.subject, body.knowledge_point)
    record = db.get(TeacherTeachingFocus, key)
    now = datetime.now()
    if record is None:
        db.add(TeacherTeachingFocus(teacher_id=current.id, **body.model_dump(), taught_at=now))
    elif not same_teaching_day(record.taught_at, now):
        db.query(TeacherTeachingFocus).filter(
            TeacherTeachingFocus.teacher_id == current.id,
            TeacherTeachingFocus.subject == body.subject,
            TeacherTeachingFocus.knowledge_point == body.knowledge_point,
            TeacherTeachingFocus.taught_at == record.taught_at,
        ).update({TeacherTeachingFocus.taught_at: now}, synchronize_session=False)
    try:
        db.commit()
    except IntegrityError:
        # 同一天的重复点击/并发请求不制造重复记录，也不改写本次讲解起点。
        db.rollback()
        if db.get(TeacherTeachingFocus, key) is None:
            raise
    return build_teaching_plan(db, current)
