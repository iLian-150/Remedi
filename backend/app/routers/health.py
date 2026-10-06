# /api/health
from datetime import datetime

from fastapi import APIRouter

from ..config import settings
from ..schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut, summary="健康检查")
def health():
    return HealthOut(version=settings.APP_VERSION, provider=get_provider_name(), time=datetime.now())


def get_provider_name() -> str:
    from ..services.providers import get_provider
    return type(get_provider()).__name__.replace("Provider", "").lower()
