# Remedi MVP 后端入口。
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
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


@app.get("/", include_in_schema=False)
def root():
    return {
        "name": "Remedi MVP",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
