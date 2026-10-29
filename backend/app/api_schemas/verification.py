"""Public request and response models for the verification API domain."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VerificationCreate(BaseModel):
    knowledge_point: str = Field(min_length=1, max_length=64)
    source_error_id: Optional[int] = None   # 触发验证的错题，可空（后端默认取该知识点最近错题）
    subject: Optional[str] = Field(default=None, max_length=32)

class VerificationOut(BaseModel):
    id: int
    knowledge_point: str
    prompt: str                   # 只下发题干，答案与标准步骤不下发
    status: str                   # pending | passed | failed
    attempts: int
    source_error_id: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

class VerificationSubmitIn(BaseModel):
    steps: List[str] = Field(min_length=1, max_length=20)

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

class VerificationStepOut(BaseModel):
    seq: int
    text: str
    status: str                   # ok | error | unparseable | skipped

class VerificationSubmitOut(BaseModel):
    id: int
    knowledge_point: str
    status: str                   # passed | failed
    attempts: int
    passed: bool
    first_error_seq: Optional[int] = None   # 首个出错步序号（通过时为 None）
    error_type: Optional[str] = None        # 首个出错步的错因（最终步未完成时为 None）
    detail: Optional[str] = None            # 解析/判定说明
    steps: List[VerificationStepOut]

__all__ = [
    'VerificationCreate',
    'VerificationOut',
    'VerificationSubmitIn',
    'VerificationStepOut',
    'VerificationSubmitOut',
]
