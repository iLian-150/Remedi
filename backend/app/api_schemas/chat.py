"""Public request and response models for the chat API domain."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .student import RelatedMistakeOut


class AgentChatIn(BaseModel):
    # 长度上限在接口层手动校验并返回 400（契约约定），故此处只做非空约束
    message: str = Field(min_length=1)
    session_id: Optional[int] = None  # v0.6.0 新增：指定写入的会话；不传 = 当前会话（没有则自动新建）
    persist_user_message: bool = True  # 流式接口允许复用已保存的拍照消息，避免重复记一条
    safe_tools_only: bool = False  # 拍照结果讲解只开放只读工具，避免重复写入批改记录
    related_mistake_error_id: Optional[int] = None  # 照片识别阶段查到的历史错题，避免讲解时再走工具轮次
    subject: Optional[str] = Field(
        default=None,
        pattern="^(chinese|math|english|politics|history|physics|chemistry|geography|biology)$",
    )

class AgentAssistantMessageIn(BaseModel):
    """保存直接视觉问答生成的助手回复；用户图片消息已由拍照接口保存。"""
    content: str = Field(min_length=1, max_length=20000)
    related_mistake_error_id: Optional[int] = None

class AgentHistoryItem(BaseModel):
    role: str                     # user | assistant
    content: str
    created_at: datetime
    related_mistake: Optional[RelatedMistakeOut] = None
    image_url: Optional[str] = None
    image_name: Optional[str] = None

class AgentHistoryPageOut(BaseModel):
    items: List[AgentHistoryItem]
    has_more: bool
    before_created_at: Optional[datetime] = None
    before_id: Optional[int] = None

class ChatSessionOut(BaseModel):
    """对话会话（v0.6.0 新增）：历史对话列表用。"""
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int

class ChatSessionPageOut(BaseModel):
    items: List[ChatSessionOut]
    has_more: bool
    before_updated_at: Optional[datetime] = None
    before_id: Optional[int] = None

class NotificationItem(BaseModel):
    id: int
    type: str
    content: str
    related_submission_id: Optional[int] = None
    is_read: bool
    created_at: datetime

class NotificationListOut(BaseModel):
    unread_count: int
    items: List[NotificationItem]

class NotificationUnreadCountOut(BaseModel):
    unread_count: int

class NotificationReadIn(BaseModel):
    ids: Optional[List[int]] = None   # 不传或为空 = 全部标已读

class NotificationReadOut(BaseModel):
    updated: int                  # 本次标已读的条数
    unread_count: int             # 标后的未读数

__all__ = [
    'AgentChatIn',
    'AgentAssistantMessageIn',
    'AgentHistoryItem',
    'AgentHistoryPageOut',
    'ChatSessionOut',
    'ChatSessionPageOut',
    'NotificationItem',
    'NotificationListOut',
    'NotificationUnreadCountOut',
    'NotificationReadIn',
    'NotificationReadOut',
]
