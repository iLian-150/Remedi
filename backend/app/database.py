# 数据库连接与会话管理。
# 只用 SQLAlchemy 标准 API；默认值一律 Python 侧赋值，不用 server_default，保证 PG 兼容。
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite 线程安全：允许跨线程使用同一连接（配合 scoped 使用习惯）
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """建表并幂等补齐会话消息读取索引（MVP 用；生产请用 Alembic 迁移）。"""
    from . import models  # noqa: F401  确保模型被注册到 Base.metadata
    Base.metadata.create_all(bind=engine)
    # create_all 不会给已存在的表补建后来添加的索引；启动时显式幂等创建热查询表索引。
    for model in (models.SubmissionReview, models.Correction, models.Verification):
        for index in model.__table__.indexes:
            index.create(bind=engine, checkfirst=True)
    for index in models.ChatSessionMessage.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
