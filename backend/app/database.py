# 数据库连接与会话管理。
# 只用 SQLAlchemy 标准 API；默认值一律 Python 侧赋值，不用 server_default，保证 PG 兼容。
from sqlalchemy import create_engine, inspect, text
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
    """建表并幂等补齐轻量 schema 更新与热查询索引。"""
    from . import models  # noqa: F401  确保模型被注册到 Base.metadata
    Base.metadata.create_all(bind=engine)
    # 会话列表读取持久化消息数；老库只在新增列时回填一次，不在每次请求中聚合历史消息。
    with engine.begin() as connection:
        session_columns = {
            column["name"]
            for column in inspect(connection).get_columns("chat_sessions")
        }
        if "message_count" not in session_columns:
            connection.execute(text(
                "ALTER TABLE chat_sessions "
                "ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0"
            ))
            connection.execute(text(
                "UPDATE chat_sessions SET message_count = "
                "(SELECT COUNT(*) FROM chat_session_messages "
                "WHERE chat_session_messages.session_id = chat_sessions.id)"
            ))
    # create_all 不会给已存在的表补建后来添加的索引；启动时显式幂等创建热查询表索引。
    for model in (
        models.Submission,
        models.Notification,
        models.SubmissionReview,
        models.Correction,
        models.Verification,
    ):
        for index in model.__table__.indexes:
            index.create(bind=engine, checkfirst=True)
    for index in models.ChatSessionMessage.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
