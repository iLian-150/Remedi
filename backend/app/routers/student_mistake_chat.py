"""错题本专属问答接口，不读取或写入主页 chat_sessions。"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_student
from ..database import get_db
from ..models import User
from ..services import mistake_chat
from ..services.streaming import ClosingStreamingResponse

router = APIRouter(prefix="/api/student/mistakes", tags=["student"])
logger = logging.getLogger(__name__)


class MistakeChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class MistakeChatMessageOut(BaseModel):
    role: str
    content: str


@router.get("/{mistake_id}/chat", response_model=list[MistakeChatMessageOut], summary="读取本题专属问答")
def history(mistake_id: int, db: Session = Depends(get_db), current: User = Depends(require_student)):
    mistake_chat.owned_mistake_context(db, current.id, mistake_id)
    return [{"role": row.role, "content": row.content}
            for row in mistake_chat.message_history(db, current.id, mistake_id)]


@router.post("/{mistake_id}/chat/stream", summary="与本题学习助手流式对话")
def chat(mistake_id: int, body: MistakeChatIn,
         db: Session = Depends(get_db), current: User = Depends(require_student)):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "消息不能为空")
    context = mistake_chat.owned_mistake_context(db, current.id, mistake_id)
    rows = mistake_chat.message_history(db, current.id, mistake_id)
    student_id = current.id

    def event(name: str, payload: dict):
        return f"event: {name}\ndata: {json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n\n"

    def events():
        yield ": connected\n\n"
        stream = mistake_chat.reply_stream(db, context, rows, text)
        try:
            parts = []
            for chunk in stream:
                parts.append(chunk)
                yield event("token", {"text": chunk})
            reply = "".join(parts).strip()
            if not reply:
                raise ValueError("Empty mistake explanation")
            mistake_chat.save_exchange(db, student_id, mistake_id, text, reply)
            yield event("done", {"reply": reply, "suggestions": [], "session_id": None})
        except Exception as exc:
            db.rollback()
            # 不记录原始上游响应或凭证。
            logger.warning("错题讲解失败（student_id=%s, mistake_id=%s, error_type=%s）",
                           student_id, mistake_id, type(exc).__name__)
            yield event("error", {"detail": "暂时无法生成讲解，请稍后重试。"})
        finally:
            stream.close()

    return ClosingStreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })
