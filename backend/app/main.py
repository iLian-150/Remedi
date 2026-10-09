# Remedi MVP 后端入口。
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, init_db
from .services import deferral as deferral_svc
from .routers import auth as auth_router
from .routers import health as health_router
from .routers import student as student_router
from .routers import teacher as teacher_router

app = FastAPI(
    title="Remedi MVP",
    description="多学科智能作业批改与学习诊断系统（MVP）",
    version=settings.APP_VERSION,
)

# CORS：允许前端 dev server 跨域。CORS_ORIGINS="*" 或逗号分隔的来源列表。
origins = (
    ["*"] if settings.CORS_ORIGINS.strip() == "*"
    else [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(health_router.router)
app.include_router(student_router.router)
app.include_router(teacher_router.router)

# 拍照上传的图片以静态文件方式回读（前端转写卡片预览用）
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.on_event("startup")
def _startup():
    init_db()


async def _deferred_grading_loop() -> None:
    """延迟批改清扫（v0.13.1）：每分钟检查一次到期的「允许修改」作业，
    把截止前收到的延迟提交统一批改。单容器单 worker 部署下进程内循环即可；
    清扫失败只跳过本轮，绝不拖垮主服务。"""
    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                deferral_svc.grade_due(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


@app.on_event("startup")
async def _start_deferred_grading() -> None:
    asyncio.create_task(_deferred_grading_loop())


@app.get("/", include_in_schema=False)
def root():
    return {
        "name": "Remedi MVP",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
