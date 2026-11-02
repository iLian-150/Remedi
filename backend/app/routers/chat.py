"""Shared authenticated endpoints for student and teacher chat."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from ..auth import get_current_user
from ..services.chat_attachments import MAX_CHAT_ATTACHMENT_BYTES, extract_chat_attachment

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/attachments/extract", summary="读取对话附件")
async def extract_attachment(
    file: UploadFile = File(...),
    current=Depends(get_current_user),
):
    if current.role not in {"student", "teacher"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该接口仅供学生和教师使用。")
    data = await file.read(MAX_CHAT_ATTACHMENT_BYTES + 1)
    if len(data) > MAX_CHAT_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件不能超过 100MB。")
    try:
        return await run_in_threadpool(extract_chat_attachment, data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
