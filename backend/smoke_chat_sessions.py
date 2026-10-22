"""Chat session migration regressions: python smoke_chat_sessions.py."""
import faulthandler
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ChatMessage, ChatSession, ChatSessionMessage, User
from app.services.chat_sessions import ensure_migrated, list_sessions


class ChatSessionMigrationTests(unittest.TestCase):
    def setUp(self):
        faulthandler.dump_traceback_later(15, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.temporary = tempfile.TemporaryDirectory(prefix="remedi-chat-migration-")
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(self.temporary.name) / 'chat.sqlite'}",
            connect_args={"check_same_thread": False, "timeout": 2},
            future=True,
        )
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            user = User(name="并发迁移学生", role="student")
            db.add(user)
            db.flush()
            self.user_id = user.id
            self.db_user = User(id=user.id, name=user.name, role=user.role)
            db.add_all([
                ChatMessage(user_id=user.id, role="user", content=f"旧消息 {index}")
                for index in range(3)
            ])
            db.commit()

    def test_parallel_first_visit_migrates_legacy_messages_once(self):
        barrier = threading.Barrier(2)
        thread_state = threading.local()

        def pause_after_both_requests_observe_no_session(
            _connection, _cursor, statement, _parameters, _context, _executemany,
        ):
            sql = statement.lower()
            if "from chat_sessions" in sql and "user_id" in sql and not getattr(thread_state, "waited", False):
                thread_state.waited = True
                barrier.wait(timeout=5)

        event.listen(self.engine, "after_cursor_execute", pause_after_both_requests_observe_no_session)

        def request_migration():
            with Session(self.engine) as db:
                return list_sessions(db, self.db_user)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request_migration) for _ in range(2)]
                results = [future.result(timeout=8) for future in futures]
        finally:
            event.remove(self.engine, "after_cursor_execute", pause_after_both_requests_observe_no_session)

        self.assertEqual([len(result) for result in results], [1, 1])
        self.assertTrue(all(result[0]["message_count"] == 3 for result in results))
        with Session(self.engine) as db:
            sessions = db.query(ChatSession).filter_by(user_id=self.user_id).all()
            messages = db.query(ChatSessionMessage).join(ChatSession).filter(
                ChatSession.user_id == self.user_id,
            ).order_by(ChatSessionMessage.id).all()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].message_count, 3)
            self.assertEqual([message.content for message in messages], ["旧消息 0", "旧消息 1", "旧消息 2"])
            self.assertEqual(db.query(ChatMessage).filter_by(user_id=self.user_id).count(), 0)

    def test_single_first_visit_preserves_legacy_message_order(self):
        with Session(self.engine) as db:
            self.assertTrue(ensure_migrated(db, self.db_user))
            self.assertFalse(ensure_migrated(db, self.db_user))
            session = db.query(ChatSession).filter_by(user_id=self.user_id).one()
            messages = db.query(ChatSessionMessage).filter_by(session_id=session.id).order_by(
                ChatSessionMessage.id,
            ).all()
            self.assertEqual([message.content for message in messages], ["旧消息 0", "旧消息 1", "旧消息 2"])

    def test_stale_read_snapshot_retries_after_a_concurrent_migration(self):
        stale = Session(self.engine)
        try:
            stale.connection().exec_driver_sql("BEGIN")
            self.assertIsNone(stale.query(ChatSession.id).filter_by(user_id=self.user_id).first())
            self.assertIsNotNone(stale.query(ChatMessage.id).filter_by(user_id=self.user_id).first())
            with Session(self.engine) as current:
                self.assertTrue(ensure_migrated(current, self.db_user))
            self.assertTrue(ensure_migrated(stale, self.db_user))
        finally:
            stale.close()

        with Session(self.engine) as db:
            self.assertEqual(db.query(ChatSession).filter_by(user_id=self.user_id).count(), 1)
            self.assertEqual(db.query(ChatSessionMessage).count(), 3)
            self.assertEqual(db.query(ChatMessage).filter_by(user_id=self.user_id).count(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
