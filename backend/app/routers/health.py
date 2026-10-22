# /api/health
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut, summary="健康检查")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return HealthOut(version=settings.APP_VERSION, provider=get_provider_name(), time=datetime.now())


def get_provider_name() -> str:
    """返回配置的提供方名称；进程健康检查不初始化或探测 AI 服务。"""
    return settings.LLM_PROVIDER
