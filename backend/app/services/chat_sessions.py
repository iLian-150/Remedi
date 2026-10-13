# Agent 对话会话服务（v0.6.0 新增）：会话的增删查、当前会话解析、旧数据迁移。
#
# 背景：v0.5.0 的「新对话」是物理删除 chat_messages 里的全部记录，旧对话找不回来。
# v0.6.0 改为会话制：chat_messages 是已上线表不许加列，故新开
# chat_sessions / chat_session_messages 两张表承接，旧表只做一次性迁移后停用。
#
# 迁移口径：用户首次触碰任一会话接口时，若其在旧 chat_messages 有记录
# 且尚无任何会话 → 生成一条标题「之前的对话」的会话，把旧消息按序复制进来，
# 再删掉该用户在旧表的行（防重复迁移）。学生/教师按 user_id 各自独立迁移。
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    ChatMessage,
    ChatSession,
    ChatSessionMessage,
    ChatSessionMessageImage,
    ChatSessionMessageMistakeLink,
    User,
)

LEGACY_SESSION_TITLE = "之前的对话"
DEFAULT_SESSION_TITLE = "新对话"
TITLE_MAX_CHARS = 20


def ensure_migrated(db: Session, user: User) -> None:
    """把该用户在旧 chat_messages 的记录一次性迁入会话表（幂等，可重复调用）。"""
    has_session = (
        db.query(ChatSession).filter(ChatSession.user_id == user.id).first()
    )
    if has_session:
        return
    legacy = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    if not legacy:
        return
    session = ChatSession(
        user_id=user.id,
        title=LEGACY_SESSION_TITLE,
        created_at=legacy[0].created_at,
        updated_at=legacy[-1].created_at,
    )
    db.add(session)
    db.flush()  # 先拿到 session.id 再挂消息
    for row in legacy:
        db.add(ChatSessionMessage(
            session_id=session.id,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        ))
    db.query(ChatMessage).filter(ChatMessage.user_id == user.id) \
        .delete(synchronize_session=False)
    db.commit()


def create_session(db: Session, user: User, title: str = DEFAULT_SESSION_TITLE) -> ChatSession:
    session = ChatSession(user_id=user.id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def current_session(db: Session, user: User) -> Optional[ChatSession]:
    """当前会话 = 最近更新的那个；没有会话时返回 None（不自动创建）。"""
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .first()
    )


def get_or_create_current(db: Session, user: User) -> ChatSession:
    session = current_session(db, user)
    if session is None:
        session = create_session(db, user)
    return session


def get_own_session(db: Session, user: User, session_id: int) -> Optional[ChatSession]:
    """只查本人的会话；不存在或不是本人的统一返回 None（接口层转 404）。"""
    return (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )


def list_sessions(db: Session, user: User) -> List[dict]:
    message_counts = (
        db.query(
            ChatSessionMessage.session_id.label("session_id"),
            func.count(ChatSessionMessage.id).label("message_count"),
        )
        .join(ChatSession, ChatSession.id == ChatSessionMessage.session_id)
        .filter(ChatSession.user_id == user.id)
        .group_by(ChatSessionMessage.session_id)
        .subquery()
    )
    rows = (
        db.query(
            ChatSession,
            func.coalesce(message_counts.c.message_count, 0),
        )
        .outerjoin(message_counts, message_counts.c.session_id == ChatSession.id)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "message_count": int(message_count),
        }
        for s, message_count in rows
    ]


def session_messages(db: Session, session: ChatSession,
                     limit: Optional[int] = None) -> List[ChatSessionMessage]:
    """会话内消息正序返回；limit 给定时取最近 limit 条（仍正序）。"""
    query = (
        db.query(ChatSessionMessage)
        .filter(ChatSessionMessage.session_id == session.id)
        .order_by(ChatSessionMessage.created_at.desc(), ChatSessionMessage.id.desc())
    )
    if limit is not None:
        rows = query.limit(limit).all()
        return list(reversed(rows))
    rows = query.all()
    return list(reversed(rows))


def history_items(db: Session, user: User, session: ChatSession,
                  limit: Optional[int] = None) -> List[dict]:
    """批量组装会话历史，避免逐条查询图片和错题关联 ID。"""
    messages = session_messages(db, session, limit)
    if not messages:
        return []
    message_filter = ChatSessionMessage.session_id == session.id
    if limit is not None and len(messages) <= 500:
        message_filter = ChatSessionMessage.id.in_([message.id for message in messages])

    image_by_message = {
        message_id: {
            "image_url": f"/api/uploads/{file_path}",
            "image_name": file_name,
        }
        for message_id, file_path, file_name in (
            db.query(
                ChatSessionMessageImage.message_id,
                ChatSessionMessageImage.file_path,
                ChatSessionMessageImage.file_name,
            )
            .join(
                ChatSessionMessage,
                ChatSessionMessage.id == ChatSessionMessageImage.message_id,
            )
            .filter(message_filter)
            .all()
        )
    }
    mistake_error_by_message = dict(
        db.query(
            ChatSessionMessageMistakeLink.message_id,
            ChatSessionMessageMistakeLink.error_id,
        )
        .join(
            ChatSessionMessage,
            ChatSessionMessage.id == ChatSessionMessageMistakeLink.message_id,
        )
        .filter(message_filter)
        .all()
    )

    from .related_mistakes import find_related_mistake_for_error

    related_by_error = {}
    result = []
    for message in messages:
        error_id = mistake_error_by_message.get(message.id)
        related = None
        if message.role == "assistant" and error_id is not None:
            if error_id not in related_by_error:
                related_by_error[error_id] = find_related_mistake_for_error(
                    db, user.id, error_id
                )
            related = related_by_error[error_id]
        item = {
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
            "related_mistake": related,
        }
        item.update(image_by_message.get(message.id, {}))
        result.append(item)
    return result


def append_message(db: Session, session: ChatSession, role: str, content: str) -> ChatSessionMessage:
    """往会话追加一条消息并刷新 updated_at；
    第一条用户消息到达且标题仍是默认「新对话」时，自动把标题改为该消息前 20 字。"""
    msg = ChatSessionMessage(session_id=session.id, role=role, content=content)
    db.add(msg)
    if role == "user" and session.title == DEFAULT_SESSION_TITLE:
        has_user_msg = (
            db.query(ChatSessionMessage)
            .filter(ChatSessionMessage.session_id == session.id,
                    ChatSessionMessage.role == "user")
            .first()
        )
        if has_user_msg is None:
            session.title = content.strip()[:TITLE_MAX_CHARS] or DEFAULT_SESSION_TITLE
    session.updated_at = datetime.now()
    db.commit()
    db.refresh(msg)
    return msg


def attach_image(db: Session, message: ChatSessionMessage,
                 file_path: str, file_name: str) -> None:
    """将已保存的图片路径关联到会话消息。"""
    db.merge(ChatSessionMessageImage(
        message_id=message.id,
        file_path=file_path,
        file_name=file_name[:255],
    ))
    db.commit()


def image_for_message(db: Session, message: ChatSessionMessage) -> Optional[dict]:
    image = db.query(ChatSessionMessageImage).filter_by(message_id=message.id).first()
    if image is None:
        return None
    return {
        "image_url": f"/api/uploads/{image.file_path}",
        "image_name": image.file_name,
    }


def link_related_mistake(db: Session, message: ChatSessionMessage,
                         error_id: Optional[int]) -> None:
    """将一条助手回复与其历史错题入口关联，支持会话恢复。"""
    if error_id is None:
        return
    link = ChatSessionMessageMistakeLink(message_id=message.id, error_id=error_id)
    db.merge(link)
    db.commit()


def related_mistake_for_message(db: Session, user: User,
                                message: ChatSessionMessage) -> Optional[dict]:
    if message.role != "assistant":
        return None
    link = db.query(ChatSessionMessageMistakeLink).filter_by(
        message_id=message.id
    ).first()
    if link is None:
        return None
    from .related_mistakes import find_related_mistake_for_error

    return find_related_mistake_for_error(db, user.id, link.error_id)


def delete_session(db: Session, user: User, session_id: int) -> bool:
    """删除本人的一条会话及其全部消息；不存在/非本人返回 False。"""
    session = get_own_session(db, user, session_id)
    if session is None:
        return False
    message_ids = [row[0] for row in db.query(ChatSessionMessage.id)
                   .filter(ChatSessionMessage.session_id == session.id).all()]
    if message_ids:
        db.query(ChatSessionMessageImage).filter(
            ChatSessionMessageImage.message_id.in_(message_ids)
        ).delete(synchronize_session=False)
        db.query(ChatSessionMessageMistakeLink).filter(
            ChatSessionMessageMistakeLink.message_id.in_(message_ids)
        ).delete(synchronize_session=False)
    db.query(ChatSessionMessage) \
        .filter(ChatSessionMessage.session_id == session.id) \
        .delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return True
