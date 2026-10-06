# Pydantic 请求/响应模型。与 api-contract.md 的 JSON 示例一一对应。
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- 通用 ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    student_no: Optional[str] = None
    role: str


class Pagination(BaseModel):
    total: int
    items: list


# ---------- 认证 ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(teacher|student)$")


class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 学生：作业 ----------

class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    knowledge_point: str
    stem: str
    order_num: int


class AssignmentBrief(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    question_count: int
    created_at: datetime


class AssignmentDetail(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    questions: List[QuestionOut]


# ---------- 学生：数学诊断 ----------

class SubmissionCreate(BaseModel):
    question_id: int
    steps: List[str] = Field(min_length=1, max_length=20)

    # 每个步骤非空、限长
    from pydantic import field_validator

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, v: List[str]) -> List[str]:
        cleaned = []
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("每个作答步骤不能为空")
            if len(s) > 500:
                raise ValueError("单个步骤不能超过 500 字符")
            cleaned.append(s.strip())
        return cleaned


class StepOut(BaseModel):
    seq: int
    text: str
    status: str


class ErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    submission_id: int
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    knowledge_point: str
    error_type: str
    confidence: float
    is_stubborn: bool
    detail: Optional[str] = None
    teacher_corrected: bool
    teacher_note: Optional[str] = None
    created_at: datetime


class DiagnosisOut(BaseModel):
    submission_id: int
    question_id: int
    status: str
    first_error_seq: Optional[int] = None
    steps: List[StepOut]
    errors: List[ErrorOut]


class SubmissionBrief(BaseModel):
    id: int
    question_id: int
    question_stem: str
    knowledge_point: str
    status: str
    error_count: int
    submitted_at: datetime


# ---------- 学生：作文 ----------

class EssayCreate(BaseModel):
    question_id: Optional[int] = None
    text: str = Field(min_length=10, max_length=2000)


class GrammarIssue(BaseModel):
    sentence_no: int
    sentence: str
    issue: str
    suggestion: str


class EssayScores(BaseModel):
    content: int
    structure: int
    grammar: int
    vocabulary: int
    expression: int
    total: int


class EssayOut(BaseModel):
    essay_id: int
    question_id: Optional[int] = None
    text: Optional[str] = None
    scores: EssayScores
    grammar_issues: List[GrammarIssue]
    overall: Optional[str] = None
    submitted_at: datetime


class EssayBrief(BaseModel):
    essay_id: int
    question_id: Optional[int] = None
    total: int
    submitted_at: datetime


# ---------- 学生：订正 ----------

class CorrectionCreate(BaseModel):
    error_id: int
    content: str = Field(min_length=1, max_length=500)


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    error_id: int
    content: str
    is_correct: Optional[bool] = None
    note: Optional[str] = None
    submitted_at: datetime


# ---------- 画像 ----------

class KnowledgePointStat(BaseModel):
    knowledge_point: str
    attempts: int
    errors: int
    error_rate: float
    mastery: float


class StubbornErrorBrief(BaseModel):
    id: int
    knowledge_point: str
    error_type: str
    step_text: Optional[str] = None
    created_at: datetime


class ProfileOut(BaseModel):
    student: UserOut
    knowledge_points: List[KnowledgePointStat]
    stubborn_errors: List[StubbornErrorBrief]
    recent_errors: List[ErrorOut]
    suggestion: str


# ---------- 教师 ----------

class TeacherErrorItem(BaseModel):
    id: int
    student: UserOut
    question: QuestionOut
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    knowledge_point: str
    error_type: str
    confidence: float
    is_stubborn: bool
    detail: Optional[str] = None
    teacher_corrected: bool
    teacher_note: Optional[str] = None
    created_at: datetime


class ErrorCorrectIn(BaseModel):
    error_type: str = Field(pattern="^(计算失误|概念混淆|审题遗漏|无法解析)$")
    teacher_note: Optional[str] = Field(default=None, max_length=1000)


class TopQuestionItem(BaseModel):
    question_id: int
    stem: str
    subject: str
    knowledge_point: str
    error_count: int
    student_count: int


class KnowledgePointRankItem(BaseModel):
    knowledge_point: str
    submissions: int
    errors: int
    error_rate: float


class StudentBrief(BaseModel):
    id: int
    name: str
    student_no: Optional[str] = None
    submission_count: int
    error_count: int


# ---------- 健康检查 ----------

class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    provider: str
    time: datetime
