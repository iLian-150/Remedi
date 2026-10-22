"""Agent 工具执行回归：真实工具和临时 SQLite，模型为本地脚本，无网络请求。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import faulthandler
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
import time
from typing import Any
import unittest
from unittest.mock import Mock, patch

from langchain_core.language_models.chat_models import BaseChatModel, generate_from_stream
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.graph import _classify_student_request, _fallback_student_route, agent_reply_stream
from app.agent.subjects import detect_subject
from app.agent.teacher_graph import teacher_agent_reply_stream
from app.database import Base
from app.models import StudentQuestionCapture, TeacherSubject, User


class ScriptedToolModel(BaseChatModel):
    rounds: list[list[dict]] = Field(default_factory=list)
    seen: list[list[Any]] = Field(default_factory=list, exclude=True)
    turn: int = 0
    gate: Any = Field(default=None, exclude=True)

    @property
    def _llm_type(self):
        return "local-tool-regression"

    def bind_tools(self, *_args, **_kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return generate_from_stream(self._stream(messages, stop, run_manager, **kwargs))

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        index = self.turn
        self.turn += 1
        if index == 0 and self.gate is not None:
            self.gate.wait(timeout=5)
        if index < len(self.rounds):
            # 每轮索引从 0 开始，与真实 Chat Completions 工具增量一致。
            calls = [{"name": call["name"], "args": json.dumps(call.get("args", {})),
                      "id": call["id"], "index": position}
                     for position, call in enumerate(self.rounds[index])]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=calls))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="已处理本次工具结果。"))


def consume(stream):
    tokens = []
    try:
        while True:
            try:
                tokens.append(next(stream))
            except StopIteration as stopped:
                result = stopped.value
                assert "".join(tokens) == result["reply"]
                return result
    finally:
        stream.close()


class AgentToolExecutionTests(unittest.TestCase):
    def setUp(self):
        # 单线程顶层 executor 会令 messages 流永远等队列；硬截止使回归明确
        # 非零退出，而非在 ThreadPoolExecutor.__exit__ 中无限等待。
        faulthandler.dump_traceback_later(20, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.directory = TemporaryDirectory()
        self.engine = create_engine(
            "sqlite:///" + str(Path(self.directory.name) / "agent.db"),
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.student = User(name="工具回归学生", role="student", student_no="agent-smoke")
        self.teacher = User(name="工具回归教师", role="teacher")
        self.db.add_all([self.student, self.teacher])
        self.db.flush()
        self.db.add(TeacherSubject(teacher_id=self.teacher.id, subject="math"))
        self.db.commit()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.enterContext(patch("requests.post", side_effect=AssertionError("unexpected HTTP request")))
        self.enterContext(patch("httpx.Client.send", side_effect=AssertionError("unexpected SDK request")))
        self.enterContext(patch("app.agent.graph._classify_student_request", return_value=("tutoring", "math")))
        self.enterContext(patch("app.agent.graph.build_subject_context", return_value=""))
        self.enterContext(patch("app.agent.graph._context_summary", return_value=""))
        self.enterContext(patch("app.agent.graph.student_memory_to_text", return_value=""))
        self.enterContext(patch("app.agent.teacher_graph._teacher_context_summary", return_value=""))

    def student_reply(self, model):
        with patch("app.agent.graph._build_llm", return_value=model):
            return consume(agent_reply_stream(self.db, self.student, [], "请处理题目和学习记录"))

    def teacher_reply(self, model):
        with patch("app.agent.teacher_graph._build_llm", return_value=model):
            return consume(teacher_agent_reply_stream(self.db, self.teacher, [], "查询班级概况与修复率"))

    def test_explicit_unknown_route_does_not_guess_one_subject_from_comparison(self):
        model = Mock()
        model.bind_tools.return_value.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "route_student_request",
                "args": {"intent": "tutoring", "subject": "unknown"},
                "id": "route-1",
            }],
        )
        with patch("app.agent.graph._build_llm", return_value=model):
            self.assertEqual(
                _classify_student_request([], "比较数学和物理的区别"),
                ("tutoring", None),
            )
            self.assertEqual(
                _classify_student_request([], "比较数学和物理的区别", "math"),
                ("tutoring", "math"),
            )

    def test_rule_subject_detection_handles_overlaps_and_ambiguity(self):
        self.assertEqual(detect_subject("生物理解题"), "biology")
        self.assertIsNone(detect_subject("比较数学和物理的区别"))
        self.assertEqual(detect_subject("比较道法和政治"), "politics")
        self.assertEqual(detect_subject("比较数学和物理的区别", "math"), "math")
        self.assertEqual(
            _fallback_student_route("比较数学和物理的区别"),
            ("tutoring", None),
        )

    def test_unknown_subject_tutoring_does_not_reinfer_a_subject_for_rag(self):
        model = ScriptedToolModel()
        with patch(
            "app.agent.graph._classify_student_request",
            return_value=("tutoring", None),
        ), patch("app.agent.graph.build_subject_context") as retrieve:
            self.student_reply(model)
        retrieve.assert_not_called()

    @contextmanager
    def observe_overlap(self, method):
        """延长 Session 操作窗口；若同轮工具并行，将可观测到真实重叠。"""
        original = getattr(self.db, method)
        mutex = Lock()
        observed = {"active": 0, "peak": 0, "calls": 0}

        def observed_call(*args, **kwargs):
            with mutex:
                observed["active"] += 1
                observed["calls"] += 1
                observed["peak"] = max(observed["peak"], observed["active"])
            try:
                time.sleep(0.03)
                return original(*args, **kwargs)
            finally:
                with mutex:
                    observed["active"] -= 1

        with patch.object(self.db, method, side_effect=observed_call):
            yield observed

    @staticmethod
    def capture_call(call_id):
        return {"name": "save_student_text_question", "id": call_id,
                "args": {"question_text": "解方程 x+1=2", "subject": "math"}}

    def test_duplicate_student_writes_in_one_round_save_only_once(self):
        model = ScriptedToolModel(rounds=[[self.capture_call("capture-1"), self.capture_call("capture-2")]])
        with self.observe_overlap("commit") as observed:
            result = self.student_reply(model)
        self.assertEqual(observed["peak"], 1)
        self.assertEqual(observed["calls"], 1)
        self.assertEqual(self.db.query(StudentQuestionCapture).count(), 1)
        self.assertEqual(result["tools_used"], ["save_student_text_question"])
        messages = [message for message in model.seen[-1] if isinstance(message, ToolMessage)]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, messages[1].content)

    def test_read_in_same_round_observes_preceding_student_write(self):
        model = ScriptedToolModel(rounds=[[
            self.capture_call("capture-1"), {"name": "get_my_mistake_notebook", "id": "notebook-1"},
        ]])
        result = self.student_reply(model)
        messages = [message for message in model.seen[-1] if isinstance(message, ToolMessage)]
        self.assertEqual([message.tool_call_id for message in messages], ["capture-1", "notebook-1"])
        self.assertIn("解方程 x+1=2", messages[1].content)
        self.assertEqual(result["tools_used"], ["save_student_text_question", "get_my_mistake_notebook"])

    def test_teacher_tools_do_not_overlap_on_the_shared_session(self):
        model = ScriptedToolModel(rounds=[[
            {"name": "get_class_overview", "id": "overview-1"},
            {"name": "get_class_repair_rate", "id": "repair-1"},
        ]])
        with self.observe_overlap("execute") as observed:
            result = self.teacher_reply(model)
        self.assertGreater(observed["calls"], 1)
        self.assertEqual(observed["peak"], 1)
        self.assertEqual(result["tools_used"], ["get_class_overview", "get_class_repair_rate"])

    def test_student_tool_names_survive_index_reuse_and_deduplicate(self):
        model = ScriptedToolModel(rounds=[
            [{"name": "get_my_mistake_notebook", "id": "notebook-1"}],
            [{"name": "get_my_report", "id": "report-1"}],
            [{"name": "get_my_mistake_notebook", "id": "notebook-2"}],
        ])
        result = self.student_reply(model)
        self.assertEqual(result["tools_used"], ["get_my_mistake_notebook", "get_my_report"])

    def test_teacher_tool_names_survive_index_reuse_and_deduplicate(self):
        model = ScriptedToolModel(rounds=[
            [{"name": "get_class_overview", "id": "overview-1"}],
            [{"name": "get_class_repair_rate", "id": "repair-1"}],
            [{"name": "get_class_overview", "id": "overview-2"}],
        ])
        result = self.teacher_reply(model)
        self.assertEqual(result["tools_used"], ["get_class_overview", "get_class_repair_rate"])

    def test_different_agent_requests_can_still_run_concurrently(self):
        gate = Barrier(2)
        student_id = self.student.id

        def reply_from_separate_request():
            with Session(self.engine, expire_on_commit=False) as db:
                student = db.get(User, student_id)
                return consume(agent_reply_stream(db, student, [], "你好"))

        with patch("app.agent.graph._build_llm", side_effect=lambda **_kwargs: ScriptedToolModel(gate=gate)):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(reply_from_separate_request) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
        self.assertTrue(all(result["reply"] == "已处理本次工具结果。" for result in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
