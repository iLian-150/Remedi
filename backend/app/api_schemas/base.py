"""Public request and response models for the base API domain."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    student_no: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None   # v0.9.0 新增（只加字段）：学生档案黑板展示「加入时间」

class Pagination(BaseModel):
    total: int
    items: list

class LoginIn(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=64)
    role: str = Field(pattern="^(teacher|student)$")
    student_no: Optional[str] = Field(default=None, min_length=1, max_length=32)
    subject: Optional[str] = Field(
        default=None,
        pattern="^(chinese|math|english|politics|history|physics|chemistry|geography|biology)$",
    )

class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut
    active_subject: Optional[str] = None

class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    knowledge_point: str
    stem: str
    order_num: int
    # v0.13.1 新增（只加字段）：所属大题 id（QuestionGroup），普通题为 None
    group_id: Optional[int] = None

class QuestionGroupOut(BaseModel):
    """大题（v0.13.1）：共享题干，成员小题见 QuestionOut.group_id。"""
    id: int
    stem: str
    order_num: int

class AssignmentBrief(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    question_count: int
    created_at: datetime
    # v0.5.0 新增（只加字段）：发布模式与线下作业信息，无 ext 行时 mode=online、其余为 null
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None
    # v0.13.23：非数学题与线下题都需要拍照提交；数学线上题使用在线步骤板。
    photo_required: bool = False

class AssignmentDetail(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    questions: List[QuestionOut]
    # v0.5.0 新增（只加字段）：同 AssignmentBrief
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None
    # v0.13.1 新增（只加字段）：允许修改开关 + 大题列表
    allow_revision: bool = False
    groups: List[QuestionGroupOut] = []

class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    provider: str
    time: datetime

__all__ = [
    'UserOut',
    'Pagination',
    'LoginIn',
    'LoginOut',
    'QuestionOut',
    'QuestionGroupOut',
    'AssignmentBrief',
    'AssignmentDetail',
    'HealthOut',
]
