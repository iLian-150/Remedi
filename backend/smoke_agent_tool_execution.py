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
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.graph import _classify_student_request, _fallback_student_route, agent_reply_stream
from app.agent.subjects import detect_subject
from app.agent.suggestions import teacher_intent, teacher_suggestions
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
        self.assertEqual(detect_subject("Explain force in physics"), "physics")
        self.assertEqual(detect_subject("Mathematics homework"), "math")
        self.assertIsNone(detect_subject("metaphysics"), "英文科目名必须按完整单词匹配")
        self.assertIsNone(detect_subject("Compare math and physics"))
        self.assertEqual(
            _fallback_student_route("比较数学和物理的区别"),
            ("tutoring", None),
        )
        self.assertEqual(
            _fallback_student_route("Explain force in physics"),
            ("tutoring", "physics"),
        )

    def test_teacher_followup_suggestions_match_rag_and_teaching_tools(self):
        knowledge = teacher_suggestions("求讲解", ["search_teaching_knowledge"])
        self.assertEqual(teacher_intent("求讲解", ["search_teaching_knowledge"]), "knowledge")
        self.assertIn("课堂讲解提纲", knowledge[0])
        self.assertIn("课堂练习", knowledge[1])

        teaching = teacher_suggestions("给教学建议", ["get_teaching_suggestions"])
        self.assertEqual(teacher_intent("给教学建议", ["get_teaching_suggestions"]), "teaching_suggestions")
        self.assertIn("分层讲解", teaching[0])
        self.assertIn("辅导顺序", teaching[1])

    def test_teacher_student_profile_returns_student_number_only_when_requested(self):
        from app.agent.teacher_tools import build_teacher_tools

        with patch(
            "app.agent.teacher_tools._teacher_scope",
            return_value=([], [self.student.id]),
        ):
            profile_tool = next(
                tool for tool in build_teacher_tools(self.db, self.teacher)
                if tool.name == "get_student_profile"
            )
            summary = profile_tool.invoke({"student_name": self.student.name})
            identified = profile_tool.invoke({
                "student_name": self.student.name,
                "include_student_no": True,
            })

        self.assertNotIn(self.student.student_no, summary)
        self.assertIn(f"学号：{self.student.student_no}", identified)

    def test_teacher_assignment_status_only_lists_students_in_authorized_classes(self):
        from app.agent.teacher_tools import build_teacher_tools
        from app.models import (
            Assignment, AssignmentClass, Classroom, ClassroomMember,
            ClassroomTeacherSubject, Question,
        )

        other_teacher = User(name="其他班教师", role="teacher")
        other_student = User(name="非任教班学生", role="student", student_no="outside-class")
        unrelated_student = User(name="本教师其他班学生", role="student", student_no="unrelated-class")
        self.db.add_all([other_teacher, other_student, unrelated_student])
        self.db.flush()
        own_class = Classroom(name="任教班", created_by=self.teacher.id)
        unrelated_own_class = Classroom(name="本教师另一任教班", created_by=self.teacher.id)
        other_class = Classroom(name="其他班", created_by=other_teacher.id)
        self.db.add_all([own_class, unrelated_own_class, other_class])
        self.db.flush()
        self.db.add_all([
            ClassroomTeacherSubject(
                classroom_id=own_class.id, teacher_id=self.teacher.id, subject="math",
            ),
            ClassroomTeacherSubject(
                classroom_id=unrelated_own_class.id,
                teacher_id=self.teacher.id, subject="math",
            ),
            ClassroomMember(classroom_id=own_class.id, student_id=self.student.id),
            ClassroomMember(classroom_id=unrelated_own_class.id, student_id=unrelated_student.id),
            ClassroomMember(classroom_id=other_class.id, student_id=other_student.id),
        ])
        assignment = Assignment(title="跨班数学作业", created_by=other_teacher.id)
        self.db.add(assignment)
        self.db.flush()
        self.db.add_all([
            Question(
                assignment_id=assignment.id, subject="math", knowledge_point="方程",
                stem="x+1=2", standard_answer="1", order_num=1,
            ),
            AssignmentClass(assignment_id=assignment.id, classroom_id=own_class.id),
            AssignmentClass(assignment_id=assignment.id, classroom_id=other_class.id),
        ])
        self.db.commit()

        profile_tool = next(
            tool for tool in build_teacher_tools(self.db, self.teacher)
            if tool.name == "get_assignment_status"
        )
        result = profile_tool.invoke({"assignment_hint": "跨班数学作业"})
        self.assertIn(self.student.name, result)
        self.assertNotIn(other_student.name, result)
        self.assertNotIn(unrelated_student.name, result)

    def test_unknown_subject_tutoring_does_not_reinfer_a_subject_for_rag(self):
        model = ScriptedToolModel()
        with patch(
            "app.agent.graph._classify_student_request",
            return_value=("tutoring", None),
        ), patch("app.agent.graph.build_subject_context") as retrieve:
            self.student_reply(model)
        retrieve.assert_not_called()

    def test_student_rag_followup_reuses_recent_question_as_search_context(self):
        history = [
            HumanMessage(content="二次函数 y=x^2-4x+3 的对称轴是多少？"),
            AIMessage(content="先看二次项系数和一次项系数。"),
        ]
        model = ScriptedToolModel()
        with patch(
            "app.agent.graph._classify_student_request",
            return_value=("tutoring", "math"),
        ), patch("app.agent.graph.build_subject_context") as retrieve, patch(
            "app.agent.graph._build_llm", return_value=model,
        ):
            result = consume(agent_reply_stream(self.db, self.student, history, "为什么呢？"))
        self.assertEqual(result["reply"], "已处理本次工具结果。")
        retrieval_query = retrieve.call_args.args[2]
        self.assertIn("二次函数", retrieval_query)
        self.assertIn("为什么呢？", retrieval_query)

    def test_student_rag_followup_does_not_mix_an_explicit_other_subject(self):
        history = [
            HumanMessage(content="生物的光合作用过程是什么？"),
            AIMessage(content="植物利用光能合成有机物。"),
        ]
        model = ScriptedToolModel()
        with patch(
            "app.agent.graph._classify_student_request",
            return_value=("tutoring", "physics"),
        ), patch("app.agent.graph.build_subject_context") as retrieve, patch(
            "app.agent.graph._build_llm", return_value=model,
        ):
            consume(agent_reply_stream(self.db, self.student, history, "这个过程如何理解？"))
        retrieval_query = retrieve.call_args.args[2]
        self.assertEqual(retrieval_query, "这个过程如何理解？")

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
