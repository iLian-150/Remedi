# 数据库连接与会话管理。
# 只用 SQLAlchemy 标准 API；默认值一律 Python 侧赋值，不用 server_default，保证 PG 兼容。
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # 请求与后台批改可能同时访问数据库：允许跨线程使用，并等待写锁最多 30 秒。
    connect_args = {"check_same_thread": False, "timeout": 30}

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
    if engine.dialect.name == "sqlite":
        # WAL 允许读请求与写事务并行；SQLite 仍然一次只能有一个写事务。
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
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
        models.User,
        models.Submission,
        models.Step,
        models.Notification,
        models.SubmissionReview,
        models.Correction,
        models.Question,
        models.QuestionGroup,
        models.Essay,
        models.Verification,
        models.StudentMistakeCategoryReview,
        models.StudentMistakeArchive,
        models.SubmissionImage,
        models.ChatSessionMessageImage,
        models.Workbook,
        models.AssignmentExt,
        models.StudentQuestionCapture,
        models.ChatSession,
    ):
        for index in model.__table__.indexes:
            index.create(bind=engine, checkfirst=True)
    # 新的复合索引覆盖旧单列索引的查询用途。
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_chat_sessions_user_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_notifications_user_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_essays_student_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_verifications_student_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_verifications_knowledge_point"))
        connection.execute(text("DROP INDEX IF EXISTS ix_verifications_student_source_error_created"))
        connection.execute(text("DROP INDEX IF EXISTS ix_questions_assignment_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_steps_submission_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_question_groups_assignment_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_chat_session_messages_session_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_submissions_student_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_student_question_captures_student_id"))
        connection.execute(text("DROP INDEX IF EXISTS ix_student_question_captures_saved_at"))
        connection.execute(text("DROP INDEX IF EXISTS ix_student_mistake_events_student_id"))
    for index in models.ChatSessionMessage.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
