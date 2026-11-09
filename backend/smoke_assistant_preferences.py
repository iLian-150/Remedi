"""回答偏好的跨会话持久化与资料隔离回归。"""
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ChatSession, ChatSessionMessage, StudentAssistantPreference, User
from app.services.assistant_preferences import extract_styles, preference_context
from app.services.chat_sessions import pack_message_content


class AssistantPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.db.add_all([User(id=1, name="学生甲", role="student"), User(id=2, name="学生乙", role="student")])
        self.db.add_all([ChatSession(id=1, user_id=1), ChatSession(id=2, user_id=1), ChatSession(id=3, user_id=2)])
        self.db.commit()

    def add_message(self, session_id, content, role="user"):
        self.db.add(ChatSessionMessage(session_id=session_id, role=role, content=content))
        self.db.commit()

    def test_old_preference_is_available_across_sessions_and_database_connections(self):
        self.add_message(1, "我喜欢简洁的回答")
        self.add_message(2, "我喜欢什么风格的回答")
        self.assertIn("喜欢简洁", preference_context(self.db, 1))
        with Session(self.engine) as reopened:
            self.assertIn("喜欢简洁", preference_context(reopened, 1))
            self.assertEqual(reopened.get(StudentAssistantPreference, 1).styles_json, '["concise"]')
        self.assertNotIn("喜欢简洁", preference_context(self.db, 2))

    def test_new_explicit_preference_replaces_old_and_forgetting_is_not_replayed(self):
        self.add_message(1, "我喜欢简洁的回答")
        preference_context(self.db, 1)
        self.add_message(2, "以后回答详细一点")
        self.assertIn("喜欢详细", preference_context(self.db, 1))
        self.add_message(2, "忘记我的回答偏好")
        self.assertIn("尚未记录", preference_context(self.db, 1))
        self.assertIn("尚未记录", preference_context(self.db, 1))

    def test_assistant_attachments_and_quoted_exercises_do_not_create_preferences(self):
        self.add_message(1, "我喜欢简洁的回答", role="assistant")
        self.add_message(1, pack_message_content("帮我分析附件", "资料.txt", "我喜欢简洁的回答"))
        self.add_message(1, '请翻译“我喜欢简洁的回答”')
        self.add_message(3, "我喜欢简洁的回答")
        self.assertIn("尚未记录", preference_context(self.db, 1))

    def test_mistake_chat_can_update_shared_preference_without_sharing_conversations(self):
        self.assertIn("结合例子", preference_context(self.db, 1, "以后请多举例讲解"))
        self.assertIn("结合例子", preference_context(self.db, 1))
        self.assertEqual(self.db.query(ChatSessionMessage).count(), 0)

    def test_questions_negations_and_unrelated_likes_are_not_assertions(self):
        for text in ["我喜欢什么风格的回答", "我不喜欢简洁的回答", "我喜欢数学", "如果我喜欢简洁的回答呢", "请详细解释这道题"]:
            self.assertIsNone(extract_styles(text), text)

    def test_smalltalk_model_receives_preferences_without_old_conversation_history(self):
        from langchain_core.messages import AIMessageChunk
        from app.agent.graph import agent_reply_stream

        self.add_message(1, "我喜欢简洁的回答")
        captured = []

        class FakeGraph:
            def __init__(self, *args): pass
            def add_node(self, *args): pass
            def add_edge(self, *args): pass
            def compile(self): return self
            def stream(self, state, **kwargs):
                captured.extend(state["messages"])
                yield {"type": "messages", "data": (AIMessageChunk(content="你喜欢简洁的回答。"), {"langgraph_node": "agent"})}

        with (patch("app.agent.graph._build_llm", return_value=object()),
              patch("app.agent.graph._classify_student_request", return_value=("smalltalk", None)),
              patch("app.agent.graph.build_tools", return_value=([], {})),
              patch("app.agent.graph.student_memory_to_text", side_effect=AssertionError("不应读取学科统计")),
              patch("langgraph.graph.StateGraph", FakeGraph)):
            chunks = list(agent_reply_stream(self.db, self.db.get(User, 1), [], "我喜欢什么风格的回答"))
        self.assertIn("喜欢简洁", captured[0].content)
        self.assertEqual(len(captured), 2)
        self.assertEqual("".join(chunks), "你喜欢简洁的回答。")


if __name__ == "__main__":
    unittest.main()
