"""Agent 工具执行回归：真实工具和临时 SQLite，模型为本地脚本，无网络请求。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import faulthandler
import json
from datetime import datetime, timedelta
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
from fastapi import HTTPException

from app.agent.graph import _classify_student_request, _fallback_student_route, agent_reply_stream
from app.agent.subjects import detect_subject
from app.agent.suggestions import teacher_intent, teacher_suggestions
from app.agent.teacher_graph import teacher_agent_reply_stream
from app.agent.teacher_tools import build_teacher_tools
from app.database import Base
from app.models import (
    Assignment,
    AssignmentClass,
    Classroom,
    ClassroomMember,
    ClassroomTeacherSubject,
    Error,
    Essay,
    Notification,
    Question,
    StudentQuestionCapture,
    Submission,
    SubmissionReview,
    SubmissionScore,
    TeacherSubject,
    User,
)
from app.services.stats import class_repair_rate, student_profile
from app.services.teacher_scope import (
    teacher_assignment_ids,
    teacher_assignment_student_ids,
    teacher_essay_ids,
    teacher_student_ids,
    teacher_submission_ids,
)
from app.services.teacher_stats import class_overview, uncorrected_overview
from app.routers.teacher import (
    _teacher_assignments_out,
    delete_assignment,
    remind_assignment,
)


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

    def test_legacy_database_migration_adds_essay_status(self):
        from sqlalchemy import inspect, text
        from app import database

        directory = TemporaryDirectory()
        engine = create_engine("sqlite:///" + str(Path(directory.name) / "legacy.db"))
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE essays ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "student_id INTEGER NOT NULL, question_id INTEGER, "
                    "text TEXT NOT NULL, scores_json TEXT NOT NULL, "
                    "grammar_issues_json TEXT NOT NULL, overall_comment TEXT, "
                    "submitted_at DATETIME NOT NULL)"
                )
                connection.execute(text(
                    "INSERT INTO essays (student_id, question_id, text, scores_json, "
                    "grammar_issues_json, submitted_at) VALUES "
                    "(1, 1, 'legacy essay', '{}', '[]', '2026-01-01 00:00:00')"
                ))
            with (
                patch.object(database, "engine", engine),
                patch.object(database.settings, "DATABASE_URL", "sqlite://"),
            ):
                database.init_db()
            columns = {
                column["name"] for column in inspect(engine).get_columns("essays")
            }
            with engine.connect() as connection:
                status = connection.execute(text(
                    "SELECT status FROM essays WHERE id=1"
                )).scalar_one()
            indexes = {index["name"] for index in inspect(engine).get_indexes("essays")}
            self.assertIn("status", columns)
            self.assertEqual(status, "submitted")
            self.assertIn("ix_essays_status_submitted_id", indexes)
            self.assertIn("ix_essays_student_question_submitted_id", indexes)
        finally:
            engine.dispose()
            directory.cleanup()

    def teacher_reply(self, model):
        with patch("app.agent.teacher_graph._build_llm", return_value=model):
            return consume(teacher_agent_reply_stream(self.db, self.teacher, [], "查询班级概况与修复率"))

    def test_deadline_timezone_uses_configured_wall_clock(self):
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from app.config import settings
        from app.models import AssignmentExt, AssignmentSetting
        from app.services.deferral import (
            assert_can_submit,
            assert_can_submit_essay,
            normalize_deadline,
        )

        received_at_utc = datetime(2026, 1, 1, 14, tzinfo=timezone.utc)
        expected = received_at_utc.astimezone(
            ZoneInfo(settings.APP_TIMEZONE)
        ).replace(tzinfo=None)
        self.assertEqual(normalize_deadline(received_at_utc), expected)

        for subject, check_submit in (
            ("math", assert_can_submit),
            ("english", assert_can_submit_essay),
        ):
            with self.subTest(subject=subject):
                assignment = Assignment(
                    title=f"时区截止回归-{subject}", created_by=self.teacher.id,
                )
                self.db.add(assignment)
                self.db.flush()
                question = Question(
                    assignment_id=assignment.id,
                    subject=subject,
                    knowledge_point="截止时间",
                    stem="时区回归问题",
                )
                self.db.add_all([
                    question,
                    AssignmentExt(
                        assignment_id=assignment.id,
                        deadline=expected - timedelta(minutes=1),
                    ),
                    AssignmentSetting(
                        assignment_id=assignment.id, allow_revision=True,
                    ),
                ])
                self.db.commit()
                with self.assertRaises(HTTPException) as expired:
                    check_submit(
                        self.db, self.student, question,
                        received_at=received_at_utc,
                    )
                self.assertEqual(expired.exception.status_code, 400)

    def test_review_deadline_uses_configured_timezone_on_utc_server(self):
        from datetime import timezone
        from app.models import AssignmentExt, SubmissionReview
        from app.services.app_time import deadline_now
        from app.services.reviews import (
            assignment_score_contexts,
            backfill_missing_review_records,
        )

        class UtcServerClock(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime.now(timezone.utc)
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        assignment = Assignment(
            title="UTC 服务器审核截止时间", created_by=self.teacher.id,
        )
        self.db.add(assignment)
        self.db.flush()
        first_question = Question(
            assignment_id=assignment.id, subject="math",
            knowledge_point="时区结算", stem="第一道结算题",
        )
        second_question = Question(
            assignment_id=assignment.id, subject="math",
            knowledge_point="时区结算", stem="第二道结算题",
        )
        submission = Submission(
            student_id=self.student.id,
            question=first_question,
            status="graded",
        )
        self.db.add_all([
            first_question,
            second_question,
            AssignmentExt(
                assignment_id=assignment.id,
                deadline=deadline_now() - timedelta(minutes=1),
            ),
            submission,
        ])
        self.db.commit()

        score_result = {submission.id: {"score": 40.0}}
        with (
            patch("app.services.reviews.datetime", UtcServerClock),
            patch("app.services.scoring.visible_scores", return_value=score_result),
        ):
            key = (self.student.id, assignment.id)
            context = assignment_score_contexts(self.db, [submission])[key]
            self.assertTrue(context["complete"])
            self.assertFalse(context["all_questions_answered"])
            self.assertEqual(backfill_missing_review_records(self.db), 1)

        review = self.db.get(SubmissionReview, submission.id)
        self.assertIsNotNone(review)
        self.assertEqual(review.status, "pending")

    def test_student_math_steps_are_parsed_without_python_eval(self):
        from app.services.mathparse import (
            UnparseableError,
            _parse_expression_cached,
            parse_step,
        )
        _parse_expression_cached.cache_clear()
        with patch("builtins.eval", side_effect=AssertionError("math input reached eval")):
            parsed = parse_step("2(x+1)=8")
            self.assertEqual(parsed.kind, "eq")
            self.assertEqual(parsed.text, "2*(x+1)=8")
            trig = parse_step("sin(x)^2+cos(x)^2")
            self.assertEqual(trig.kind, "expr")
            self.assertEqual(trig.text, "sin(x)**2+cos(x)**2")
            self.assertEqual(str(trig.expr), "sin(x)**2 + cos(x)**2")
            with self.assertRaises(UnparseableError):
                parse_step("x.__class__")

        from app.services.diagnosis import (
            detect_distributive_mistake,
            detect_sign_move_mistake,
            detect_square_mistake,
            equivalent,
        )
        self.assertTrue(equivalent(trig.expr, parse_step("1").expr))
        previous_square = parse_step("(x+2)^2")
        self.assertTrue(detect_square_mistake(
            previous_square.text, parse_step("x^2+4"),
        ))
        previous_sign = parse_step("2x+3=7")
        self.assertTrue(detect_sign_move_mistake(
            previous_sign, parse_step("2x=7+3"),
        ))
        self.assertTrue(detect_distributive_mistake(
            "2*(x-3)=10", parse_step("2*x-3=10"),
        ))

    def test_concurrent_single_submissions_are_rechecked_before_save(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, local
        from app.routers.student import submit_essay, submit_math
        from app.schemas import EssayCreate, SubmissionCreate
        from app.services import deferral as deferral_svc

        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()

        for subject in ("math", "english"):
            with self.subTest(subject=subject):
                assignment = Assignment(
                    title=f"并发单次提交-{subject}", created_by=self.teacher.id,
                )
                self.db.add(assignment)
                self.db.flush()
                question = Question(
                    assignment_id=assignment.id, subject=subject,
                    knowledge_point="并发提交", stem="并发回归题",
                )
                self.db.add(question)
                self.db.commit()
                question_id = question.id
                barrier = Barrier(2)
                thread_state = local()
                checker_name = "assert_can_submit" if subject == "math" else "assert_can_submit_essay"
                real_checker = getattr(deferral_svc, checker_name)

                def synchronized_checker(*args, **kwargs):
                    result = real_checker(*args, **kwargs)
                    if not getattr(thread_state, "initial_check_done", False):
                        thread_state.initial_check_done = True
                        barrier.wait(timeout=5)
                    return result

                scorer = Mock()
                scorer.score_essay.return_value = {
                    "scores": {
                        "content": 80, "structure": 80, "grammar": 80,
                        "vocabulary": 80, "expression": 80, "total": 80,
                    },
                    "grammar_issues": [], "overall": "作文评分完成",
                }

                def submit_once():
                    db = Session(self.engine, expire_on_commit=False)
                    try:
                        student = db.get(User, self.student.id)
                        try:
                            if subject == "math":
                                submit_math(
                                    SubmissionCreate(
                                        question_id=question_id, steps=["x=1"],
                                    ),
                                    db, student,
                                )
                            else:
                                submit_essay(
                                    EssayCreate(
                                        question_id=question_id,
                                        text="A valid concurrent essay response.",
                                    ),
                                    db, student,
                                )
                        except HTTPException as exc:
                            if exc.status_code == 400:
                                return "rejected"
                            raise
                        return "saved"
                    finally:
                        db.close()

                checker_patch = patch.object(
                    deferral_svc, checker_name, side_effect=synchronized_checker,
                )
                model_path = (
                    "app.services.diagnosis.get_provider"
                    if subject == "math" else "app.services.essays.get_provider"
                )
                with checker_patch, patch(model_path, return_value=scorer):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(lambda _index: submit_once(), range(2)))
                self.assertCountEqual(results, ["saved", "rejected"])
                if subject == "math":
                    saved_count = self.db.query(Submission).filter_by(
                        student_id=self.student.id, question_id=question_id,
                    ).count()
                else:
                    saved_count = self.db.query(Essay).filter_by(
                        student_id=self.student.id, question_id=question_id,
                    ).count()
                self.assertEqual(saved_count, 1)

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
        self.assertEqual(
            _fallback_student_route("数学中的二次函数", "physics"),
            ("tutoring", "math"),
        )

    def test_explicit_student_subject_overrides_router_guess(self):
        model = Mock()
        model.bind_tools.return_value.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "route_student_request",
                "args": {"intent": "tutoring", "subject": "physics"},
                "id": "route-subject-conflict",
            }],
        )
        with patch("app.agent.graph._build_llm", return_value=model):
            self.assertEqual(
                _classify_student_request(
                    [], "数学中的二次函数怎么求对称轴？", "english",
                ),
                ("tutoring", "math"),
            )

        model.bind_tools.return_value.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "route_student_request",
                "args": {"intent": "tutoring", "subject": "math"},
                "id": "route-subject-ambiguous",
            }],
        )
        with patch("app.agent.graph._build_llm", return_value=model):
            self.assertEqual(
                _classify_student_request([], "比较数学和物理的区别"),
                ("tutoring", None),
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

    def test_related_mistake_queries_keep_matching_rows_beyond_300_others(self):
        from app.services.related_mistakes import (
            find_related_mistake, find_related_mistakes_for_questions,
        )

        assignment = Assignment(title="大量历史错题", created_by=self.teacher.id)
        self.db.add(assignment)
        self.db.flush()
        target = Question(
            assignment_id=assignment.id, subject="english", knowledge_point="目标 知识点",
            stem="I went home yesterday.", order_num=0,
        )
        questions = [target] + [
            Question(
                assignment_id=assignment.id, subject="english",
                knowledge_point=f"其他知识点{i}", stem="I go home.", order_num=i + 1,
            )
            for i in range(300)
        ]
        self.db.add_all(questions)
        self.db.flush()
        submissions = [
            Submission(student_id=self.student.id, question_id=question.id)
            for question in questions
        ]
        self.db.add_all(submissions)
        self.db.flush()
        target_error = Error(
            submission_id=submissions[0].id, knowledge_point=target.knowledge_point,
            error_type="语法错误", confidence=0.8, detail="历史错因",
            created_at=datetime(2025, 1, 1),
        )
        self.db.add(target_error)
        self.db.add_all([
            Error(
                submission_id=submission.id, knowledge_point=question.knowledge_point,
                error_type="语法错误", confidence=0.8, detail="其他错因",
                created_at=datetime(2025, 2, 1),
            )
            for question, submission in zip(questions[1:], submissions[1:])
        ])
        self.db.commit()

        single = find_related_mistake(
            self.db, self.student.id, "english", "目标知识点",
        )
        batch = find_related_mistakes_for_questions(
            self.db, self.student.id, [target],
        )[target.id]

        self.assertEqual(single["id"], target_error.id)
        self.assertEqual(batch["id"], target_error.id)

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

    def test_teacher_student_number_visibility_follows_explicit_user_request(self):
        from app.agent.teacher_tools import build_teacher_tools

        with patch(
            "app.agent.teacher_tools._teacher_scope",
            return_value=([], [self.student.id]),
        ):
            requested_tool = next(
                item for item in build_teacher_tools(
                    self.db, self.teacher,
                    current_user_text=f"请告诉我{self.student.name}的学号。",
                )
                if item.name == "get_student_profile"
            )
            hidden_tool = next(
                item for item in build_teacher_tools(
                    self.db, self.teacher,
                    current_user_text=f"查询{self.student.name}的画像，不要显示学号。",
                )
                if item.name == "get_student_profile"
            )
            requested = requested_tool.invoke({
                "student_name": self.student.name,
                "include_student_no": False,
            })
            hidden = hidden_tool.invoke({
                "student_name": self.student.name,
                "include_student_no": True,
            })

        self.assertIn(f"学号：{self.student.student_no}", requested)
        self.assertNotIn(self.student.student_no, hidden)

    def test_teacher_student_profile_prefers_exact_names_and_rejects_mismatched_identity(self):
        from app.agent.teacher_tools import build_teacher_tools

        partial_match = User(
            name=f"{self.student.name}甲", role="student", student_no="agent-smoke-extra",
        )
        self.db.add(partial_match)
        self.db.commit()
        with patch(
            "app.agent.teacher_tools._teacher_scope",
            return_value=([], [self.student.id, partial_match.id]),
        ):
            profile_tool = next(
                tool for tool in build_teacher_tools(self.db, self.teacher)
                if tool.name == "get_student_profile"
            )
            exact = profile_tool.invoke({"student_name": self.student.name})
            mismatch = profile_tool.invoke({
                "student_name": self.student.name,
                "student_no": partial_match.student_no,
                "include_student_no": True,
            })
            wildcard = profile_tool.invoke({"student_name": "%"})

        self.assertIn(f"学生 {self.student.name} 的学习画像摘要", exact)
        self.assertNotIn(partial_match.student_no, exact)
        self.assertIn("没有找到学生", mismatch)
        self.assertNotIn(partial_match.student_no, mismatch)
        self.assertIn("没有找到学生", wildcard)

    def test_teacher_assignment_status_only_lists_students_in_authorized_classes(self):
        from app.agent.teacher_tools import build_teacher_tools
        from app.models import (
            Assignment, AssignmentClass, Classroom, ClassroomMember,
            ClassroomTeacherSubject, Error, Notification, Question, Submission,
            SubmissionReview,
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

        from app.routers.teacher import remind_assignment

        reminded = remind_assignment(assignment.id, self.db, self.teacher)
        self.assertEqual(reminded["reminded_count"], 1)
        notified_ids = {
            row[0] for row in self.db.query(Notification.user_id).filter(
                Notification.type == "teacher_reminder",
            )
        }
        self.assertEqual(notified_ids, {self.student.id})

        review_assignment = Assignment(title="跨班待审核作业", created_by=other_teacher.id)
        self.db.add(review_assignment)
        self.db.flush()
        review_question = Question(
            assignment_id=review_assignment.id, subject="math", knowledge_point="方程",
            stem="x+2=3", standard_answer="1", order_num=1,
        )
        self.db.add_all([
            review_question,
            AssignmentClass(assignment_id=review_assignment.id, classroom_id=own_class.id),
            AssignmentClass(assignment_id=review_assignment.id, classroom_id=other_class.id),
        ])
        self.db.flush()
        own_submission = Submission(student_id=self.student.id, question_id=review_question.id)
        other_submission = Submission(student_id=other_student.id, question_id=review_question.id)
        self.db.add_all([own_submission, other_submission])
        self.db.flush()
        self.db.add_all([
            SubmissionReview(submission_id=own_submission.id, status="pending"),
            SubmissionReview(submission_id=other_submission.id, status="pending"),
            Error(
                submission_id=own_submission.id, knowledge_point="方程", error_type="计算失误",
                confidence=0.9, detail="任教班诊断",
            ),
            Error(
                submission_id=other_submission.id, knowledge_point="方程", error_type="概念混淆",
                confidence=0.9, detail="其他班诊断",
            ),
        ])
        self.db.commit()

        from fastapi import HTTPException
        from app.routers.teacher import (
            correct_error, list_errors, recent_error_summaries, review_approve,
            review_detail, reviews_approve_all, reviews_pending,
            reviews_pending_count, stats_knowledge_points, stats_top_questions,
            teacher_dashboard, teaching_suggestions,
        )

        errors = list_errors(
            error_id=None, student_id=None, knowledge_point=None, error_type=None,
            stubborn_only=False, limit=20, offset=0,
            db=self.db, current=self.teacher,
        )
        self.assertEqual(errors["total"], 1)
        self.assertEqual(errors["items"][0].student.id, self.student.id)
        summaries = recent_error_summaries(limit=100, db=self.db, current=self.teacher)
        self.assertEqual([item["student"]["id"] for item in summaries["items"]], [self.student.id])
        top_questions = stats_top_questions(n=10, db=self.db, current=self.teacher)
        self.assertEqual(top_questions["items"][0].error_count, 1)
        self.assertEqual(top_questions["items"][0].student_count, 1)
        rankings = stats_knowledge_points(db=self.db, current=self.teacher)
        self.assertEqual(rankings["items"][0].submissions, 1)
        self.assertEqual(rankings["items"][0].errors, 1)
        dashboard = teacher_dashboard(
            n=10, include_suggestions=False, db=self.db, current=self.teacher,
        )
        self.assertEqual(dashboard.total_errors, 1)
        tool_ranking = next(
            tool for tool in build_teacher_tools(self.db, self.teacher)
            if tool.name == "get_knowledge_point_ranking"
        ).invoke({})
        self.assertIn("提交 1 次、出错 1 次", tool_ranking)
        suggestions = teaching_suggestions(db=self.db, current=self.teacher)
        self.assertTrue(any("提交 1 次、出错 1 次" in item["evidence"] for item in suggestions))
        other_error = self.db.query(Error).filter_by(submission_id=other_submission.id).one()
        with self.assertRaises(HTTPException) as denied_correction:
            correct_error(other_error.id, None, self.db, self.teacher)
        self.assertEqual(denied_correction.exception.status_code, 404)
        self.assertEqual(reviews_pending_count(self.db, self.teacher)["count"], 1)
        queue = reviews_pending(self.db, self.teacher)
        self.assertEqual(queue["count"], 1)
        self.assertEqual(queue["items"][0].student.id, self.student.id)
        with self.assertRaises(HTTPException) as denied_detail:
            review_detail(other_submission.id, self.db, self.teacher)
        self.assertEqual(denied_detail.exception.status_code, 404)
        with self.assertRaises(HTTPException) as denied_approval:
            review_approve(other_submission.id, None, self.db, self.teacher)
        self.assertEqual(denied_approval.exception.status_code, 404)
        with patch("app.routers.teacher.scoring_svc.finalize_on_approve_many"), patch(
            "app.services.learning_memory.refresh_student_learning_memory",
        ):
            approved = reviews_approve_all(self.db, self.teacher)
        self.assertEqual(approved["approved_count"], 1)
        self.db.expire_all()
        self.assertEqual(self.db.get(SubmissionReview, own_submission.id).status, "approved")
        self.assertEqual(self.db.get(SubmissionReview, other_submission.id).status, "pending")

    def test_legacy_mixed_assignment_status_and_reminders_respect_teacher_scope(self):
        from app.agent.teacher_tools import build_teacher_tools
        from app.models import Assignment, Classroom, ClassroomMember, ClassroomTeacherSubject

        outside_student = User(
            name="旧作业范围外学生", role="student", student_no="legacy-outside",
        )
        outside_teacher = User(name="旧作业其他教师", role="teacher")
        self.db.add_all([outside_student, outside_teacher])
        self.db.flush()
        own_class = Classroom(name="旧作业任教班", created_by=self.teacher.id)
        outside_class = Classroom(name="旧作业其他班", created_by=outside_teacher.id)
        self.db.add_all([own_class, outside_class])
        self.db.flush()
        self.db.add_all([
            ClassroomTeacherSubject(
                classroom_id=own_class.id, teacher_id=self.teacher.id,
                subject="math",
            ),
            ClassroomMember(classroom_id=own_class.id, student_id=self.student.id),
            ClassroomMember(classroom_id=outside_class.id, student_id=outside_student.id),
        ])
        assignment = Assignment(title="旧版混合学科作业", created_by=self.teacher.id)
        self.db.add(assignment)
        self.db.flush()
        math_question = Question(
            assignment_id=assignment.id, subject="math", knowledge_point="方程",
            stem="数学题", order_num=1,
        )
        physics_question = Question(
            assignment_id=assignment.id, subject="physics", knowledge_point="力学",
            stem="物理题", order_num=2,
        )
        self.db.add_all([math_question, physics_question])
        self.db.flush()
        # An unrelated subject submission must not satisfy the teacher's math
        # completion count for this legacy assignment.
        self.db.add(Submission(
            student_id=self.student.id, question_id=physics_question.id,
        ))
        self.db.commit()

        status_tool = next(
            tool for tool in build_teacher_tools(self.db, self.teacher)
            if tool.name == "get_assignment_status"
        )
        status_text = status_tool.invoke({"assignment_hint": assignment.title})
        self.assertIn("共 1 道题，班级 1 名学生", status_text)
        self.assertIn(f"完全没交 1 人：{self.student.name}", status_text)
        self.assertNotIn(outside_student.name, status_text)

        self.assertEqual(
            remind_assignment(assignment.id, self.db, self.teacher),
            {"reminded_count": 1},
        )
        notified_ids = {
            row[0] for row in self.db.query(Notification.user_id).filter_by(
                type="teacher_reminder",
            ).all()
        }
        self.assertEqual(notified_ids, {self.student.id})

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

    def test_teacher_rag_tool_uses_previous_question_for_short_followup(self):
        from langchain_core.messages import HumanMessage
        from app.models import SubjectKnowledgeChunk
        from app.services.subject_rag import prepare_knowledge

        document = SubjectKnowledgeChunk(
            subject="math", title="二次函数", source_name="教学讲义",
            content="二次函数图像是抛物线，对称轴由系数决定。",
        )
        self.db.add(document)
        prepare_knowledge(self.db, document)
        self.db.commit()
        history = [HumanMessage(content="二次函数的对称轴是什么？")]
        model = ScriptedToolModel(rounds=[[
            {
                "name": "search_teaching_knowledge", "id": "rag-followup-1",
                "args": {"query": "为什么呢？", "subject": "math"},
            },
        ]])
        with patch("app.agent.teacher_graph._build_llm", return_value=model), \
                patch("app.services.rag_milvus.configured", return_value=False), \
                patch("app.services.bailian_rerank.configured", return_value=False):
            result = consume(teacher_agent_reply_stream(
                self.db, self.teacher, history, "为什么呢？",
            ))

        tool_results = [message.content for message in model.seen[-1] if isinstance(message, ToolMessage)]
        self.assertEqual(result["tools_used"], ["search_teaching_knowledge"])
        self.assertTrue(any("教学讲义" in content for content in tool_results))
        self.assertTrue(any("教师知识库检索结果" in content for content in tool_results))

    def test_teacher_rag_uses_explicit_subject_from_original_user_message(self):
        from app.models import SubjectKnowledgeChunk
        from app.services.subject_rag import prepare_knowledge

        self.db.add(TeacherSubject(teacher_id=self.teacher.id, subject="english"))
        document = SubjectKnowledgeChunk(
            subject="english", title="现在完成时", source_name="英语讲义",
            content="现在完成时表示过去发生并持续到现在的动作或状态。",
        )
        self.db.add(document)
        prepare_knowledge(self.db, document)
        self.db.commit()
        model = ScriptedToolModel(rounds=[[
            {
                "name": "search_teaching_knowledge", "id": "rag-subject-1",
                "args": {"query": "现在完成时的用法", "subject": "math"},
            },
        ]])
        with patch("app.agent.teacher_graph._build_llm", return_value=model), \
                patch("app.services.rag_milvus.configured", return_value=False), \
                patch("app.services.bailian_rerank.configured", return_value=False):
            result = consume(teacher_agent_reply_stream(
                self.db, self.teacher, [], "英语中的现在完成时怎么用？",
            ))

        tool_results = [message.content for message in model.seen[-1] if isinstance(message, ToolMessage)]
        self.assertEqual(result["tools_used"], ["search_teaching_knowledge"])
        self.assertTrue(any("教师端英语" in content and "英语讲义" in content
                            for content in tool_results))
        self.assertFalse(any("教师端数学" in content for content in tool_results))

    def test_teacher_aggregates_filter_by_authorized_submissions(self):
        math_class = Classroom(name="逻辑回归数学班", created_by=self.teacher.id)
        physics_class = Classroom(name="逻辑回归物理班", created_by=self.teacher.id)
        physics_student = User(name="逻辑回归物理学生", role="student", student_no="agent-physics")
        unassigned_recipient = User(
            name="数学班物理作业未交学生", role="student", student_no="agent-physics-unauthorized",
        )
        assignment_owner = User(name="共享作业发布者", role="teacher")
        self.db.add_all([
            math_class, physics_class, physics_student, unassigned_recipient, assignment_owner,
        ])
        self.db.flush()
        self.db.add_all([
            TeacherSubject(teacher_id=self.teacher.id, subject="physics"),
            TeacherSubject(teacher_id=assignment_owner.id, subject="physics"),
        ])
        self.db.add_all([
            ClassroomTeacherSubject(
                classroom_id=math_class.id, teacher_id=self.teacher.id, subject="math",
            ),
            ClassroomTeacherSubject(
                classroom_id=physics_class.id, teacher_id=self.teacher.id, subject="physics",
            ),
            ClassroomMember(classroom_id=math_class.id, student_id=self.student.id),
            ClassroomMember(classroom_id=math_class.id, student_id=unassigned_recipient.id),
            ClassroomMember(classroom_id=physics_class.id, student_id=physics_student.id),
        ])
        math_assignment = Assignment(
            title="范围回归数学作业", created_by=assignment_owner.id,
        )
        physics_assignment = Assignment(
            title="范围回归物理作业", created_by=assignment_owner.id,
        )
        self.db.add_all([math_assignment, physics_assignment])
        self.db.flush()
        self.db.add_all([
            AssignmentClass(assignment_id=math_assignment.id, classroom_id=math_class.id),
            AssignmentClass(assignment_id=physics_assignment.id, classroom_id=math_class.id),
            AssignmentClass(assignment_id=physics_assignment.id, classroom_id=physics_class.id),
        ])
        math_question = Question(
            assignment_id=math_assignment.id, subject="math",
            knowledge_point="授权数学", stem="数学题",
        )
        physics_question = Question(
            assignment_id=physics_assignment.id, subject="physics",
            knowledge_point="班级物理", stem="物理题",
        )
        self.db.add_all([math_question, physics_question])
        self.db.flush()
        math_submission = Submission(student_id=self.student.id, question_id=math_question.id)
        unauthorized_submission = Submission(
            student_id=self.student.id, question_id=physics_question.id,
        )
        physics_submission = Submission(
            student_id=physics_student.id, question_id=physics_question.id,
        )
        physics_retry = Submission(
            student_id=physics_student.id, question_id=physics_question.id,
        )
        self.db.add_all([
            math_submission, unauthorized_submission, physics_submission, physics_retry,
        ])
        self.db.flush()
        self.db.add_all([
            Essay(
                student_id=self.student.id, question_id=physics_question.id,
                text="未授权作文", scores_json="{}", grammar_issues_json="[]",
            ),
            Essay(
                student_id=physics_student.id, question_id=physics_question.id,
                text="授权作文", scores_json="{}", grammar_issues_json="[]",
            ),
        ])
        self.db.add_all([
            Error(
                submission_id=math_submission.id, knowledge_point="授权数学",
                error_type="conceptual", confidence=0.9,
            ),
            Error(
                submission_id=unauthorized_submission.id, knowledge_point="越权物理",
                error_type="conceptual", confidence=0.9,
            ),
            Error(
                submission_id=physics_submission.id, knowledge_point="班级物理",
                error_type="conceptual", confidence=0.9,
            ),
        ])
        self.db.commit()

        assignments = [row[0] for row in teacher_assignment_ids(self.db, self.teacher).all()]
        students = [row[0] for row in teacher_student_ids(self.db, self.teacher).all()]
        submissions = teacher_submission_ids(self.db, self.teacher)
        essays = teacher_essay_ids(self.db, self.teacher)
        authorized_submission_ids = {row[0] for row in submissions.all()}
        self.assertEqual(
            authorized_submission_ids,
            {math_submission.id, physics_submission.id, physics_retry.id},
        )
        self.assertEqual(
            set(teacher_assignment_student_ids(
                self.db, self.teacher, physics_assignment.id,
            )),
            {physics_student.id},
        )

        overview = class_overview(self.db, assignments, students, submissions)
        self.assertEqual(overview["submission_count"], 3)
        self.assertEqual(overview["error_count"], 2)
        pending = uncorrected_overview(self.db, assignments, students, submissions)
        self.assertEqual(
            {kp for row in pending for kp in row["knowledge_points"]},
            {"授权数学", "班级物理"},
        )
        repair = class_repair_rate(self.db, students, assignments, submissions)
        self.assertEqual(repair["total_knowledge_point_pairs"], 2)
        profile = student_profile(
            self.db, self.student, assignment_ids=assignments,
            submission_ids=submissions,
        )
        self.assertEqual(
            {item["knowledge_point"] for item in profile["knowledge_points"]},
            {"授权数学"},
        )

        assignment_item = _teacher_assignments_out(
            [physics_assignment], self.db, self.teacher,
            submission_ids=submissions, essay_ids=essays,
        )[0]
        self.assertFalse(assignment_item.can_delete)
        self.assertEqual(assignment_item.questions[0].submission_count, 1)
        with self.assertRaises(HTTPException) as denied_delete:
            delete_assignment(physics_assignment.id, self.db, self.teacher)
        self.assertEqual(denied_delete.exception.status_code, 404)
        self.assertIsNotNone(self.db.get(Assignment, physics_assignment.id))
        self.assertIsNotNone(self.db.get(Submission, unauthorized_submission.id))

        tools = {item.name: item for item in build_teacher_tools(self.db, self.teacher)}
        self.assertIn("累计提交 3 次", tools["get_class_overview"].invoke({}))
        self.assertIn("共 2 组", tools["get_class_repair_rate"].invoke({}))
        self.assertNotIn("越权物理", tools["get_uncorrected_students"].invoke({}))
        assignment_status = tools["get_assignment_status"].invoke({
            "assignment_hint": "范围回归物理作业",
        })
        self.assertIn(physics_student.name, assignment_status)
        self.assertNotIn(unassigned_recipient.name, assignment_status)
        self.assertEqual(
            remind_assignment(physics_assignment.id, self.db, self.teacher),
            {"reminded_count": 0},
        )
        self.assertEqual(
            self.db.query(Notification).filter_by(user_id=unassigned_recipient.id).count(),
            0,
        )
        teacher_profile = tools["get_student_profile"].invoke({
            "student_name": self.student.name,
            "student_no": "",
            "include_student_no": False,
        })
        self.assertNotIn("越权物理", teacher_profile)
        owner_assignment = _teacher_assignments_out(
            [physics_assignment], self.db, assignment_owner,
            submission_ids=teacher_submission_ids(self.db, assignment_owner),
            essay_ids=teacher_essay_ids(self.db, assignment_owner),
        )[0]
        self.assertTrue(owner_assignment.can_delete)
        self.assertEqual(owner_assignment.questions[0].submission_count, 2)
        self.assertEqual(
            delete_assignment(physics_assignment.id, self.db, assignment_owner),
            {"deleted": True},
        )
        self.assertIsNone(self.db.get(Assignment, physics_assignment.id))

    def test_essay_submission_lock_and_deadline_deferred_scoring(self):
        from datetime import datetime, timedelta
        from fastapi import HTTPException
        from app.models import AssignmentExt, AssignmentSetting
        from app.routers.student import list_essays, submit_essay
        from app.schemas import EssayCreate, EssayOut
        from app.services.deferral import deadline_now, grade_due

        score_result = {
            "scores": {
                "content": 80, "structure": 80, "grammar": 80,
                "vocabulary": 80, "expression": 80, "total": 80,
            },
            "grammar_issues": [],
            "overall": "作文评分完成",
        }
        scorer = Mock()
        scorer.score_essay.return_value = score_result

        single_assignment = Assignment(
            title="作文单次提交", created_by=self.teacher.id,
        )
        self.db.add(single_assignment)
        self.db.flush()
        single_question = Question(
            assignment_id=single_assignment.id, subject="english",
            knowledge_point="写作", stem="Write about your school.",
        )
        self.db.add(single_question)
        self.db.commit()
        with patch("app.services.essays.get_provider", return_value=scorer):
            submitted = submit_essay(
                EssayCreate(question_id=single_question.id,
                            text="A sufficiently long first essay."),
                self.db, self.student,
            )
            self.assertEqual(submitted["status"], "submitted")
            with self.assertRaises(HTTPException) as duplicate:
                submit_essay(
                    EssayCreate(question_id=single_question.id,
                                text="A sufficiently long second essay."),
                    self.db, self.student,
                )
        self.assertEqual(duplicate.exception.status_code, 400)
        self.assertEqual(scorer.score_essay.call_count, 1)

        deferred_assignment = Assignment(
            title="作文截止统一评分", created_by=self.teacher.id,
        )
        self.db.add(deferred_assignment)
        self.db.flush()
        deferred_question = Question(
            assignment_id=deferred_assignment.id, subject="english",
            knowledge_point="写作", stem="Write about your future plans.",
        )
        deadline = deadline_now() + timedelta(hours=1)
        self.db.add_all([
            deferred_question,
            AssignmentExt(assignment_id=deferred_assignment.id, deadline=deadline),
            AssignmentSetting(
                assignment_id=deferred_assignment.id, allow_revision=True,
            ),
        ])
        self.db.commit()
        scorer.score_essay.reset_mock()
        with patch("app.services.essays.get_provider", return_value=scorer):
            first = submit_essay(
                EssayCreate(question_id=deferred_question.id,
                            text="A sufficiently long first draft."),
                self.db, self.student,
            )
            second = submit_essay(
                EssayCreate(question_id=deferred_question.id,
                            text="A sufficiently long revised draft."),
                self.db, self.student,
            )
        self.assertEqual(first["status"], "deferred")
        self.assertIsNone(first["scores"])
        self.assertEqual(EssayOut.model_validate(first).status, "deferred")
        self.assertEqual(second["status"], "deferred")
        scorer.score_essay.assert_not_called()
        essay_list = list_essays(
            limit=20, offset=0, db=self.db, current=self.student,
        )
        deferred_summaries = [
            item for item in essay_list["items"]
            if item.essay_id in {first["essay_id"], second["essay_id"]}
        ]
        self.assertEqual(len(deferred_summaries), 2)
        self.assertTrue(all(item.status == "deferred" for item in deferred_summaries))
        self.assertTrue(all(item.total is None for item in deferred_summaries))

        older = self.db.get(Essay, first["essay_id"])
        latest = self.db.get(Essay, second["essay_id"])
        older.submitted_at = datetime(2026, 1, 1)
        latest.submitted_at = datetime(2026, 1, 2)
        self.db.query(AssignmentExt).filter_by(
            assignment_id=deferred_assignment.id,
        ).update({AssignmentExt.deadline: deadline_now() - timedelta(seconds=1)})
        self.db.commit()

        with patch("app.services.deferral.get_provider", return_value=scorer):
            self.assertEqual(grade_due(self.db), 1)
            self.assertEqual(grade_due(self.db), 0)
        self.assertEqual(older.status, "superseded")
        self.assertEqual(latest.status, "submitted")
        self.assertEqual(json.loads(latest.scores_json)["total"], 80)
        scorer.score_essay.assert_called_once_with(
            text="A sufficiently long revised draft.",
            prompt=deferred_question.stem,
        )
        with self.assertRaises(HTTPException) as after_deadline:
            submit_essay(
                EssayCreate(question_id=deferred_question.id,
                            text="A sufficiently long late essay."),
                self.db, self.student,
            )
        self.assertEqual(after_deadline.exception.status_code, 400)

        open_revision_assignment = Assignment(
            title="作文无截止可修改", created_by=self.teacher.id,
        )
        self.db.add(open_revision_assignment)
        self.db.flush()
        open_revision_question = Question(
            assignment_id=open_revision_assignment.id, subject="english",
            knowledge_point="写作", stem="Write a short story.",
        )
        self.db.add_all([
            open_revision_question,
            AssignmentSetting(
                assignment_id=open_revision_assignment.id, allow_revision=True,
            ),
        ])
        self.db.commit()
        scorer.score_essay.reset_mock()
        with patch("app.services.essays.get_provider", return_value=scorer):
            open_first = submit_essay(
                EssayCreate(question_id=open_revision_question.id,
                            text="A sufficiently long open draft."),
                self.db, self.student,
            )
            open_second = submit_essay(
                EssayCreate(question_id=open_revision_question.id,
                            text="A sufficiently long revised open draft."),
                self.db, self.student,
            )
        self.assertEqual(open_first["status"], "submitted")
        self.assertEqual(open_second["status"], "submitted")
        self.assertEqual(scorer.score_essay.call_count, 2)

    def test_student_assignment_progress_counts_essay_questions_as_submitted(self):
        from app.routers.student import list_assignments

        assignment = Assignment(title="作文与数学进度", created_by=self.teacher.id)
        self.db.add(assignment)
        self.db.flush()
        math_question = Question(
            assignment_id=assignment.id, subject="math", knowledge_point="方程",
            stem="数学题", order_num=1,
        )
        essay_question = Question(
            assignment_id=assignment.id, subject="english", knowledge_point="写作",
            stem="作文题", order_num=2,
        )
        self.db.add_all([math_question, essay_question])
        self.db.flush()
        math_submission = Submission(
            student_id=self.student.id, question_id=math_question.id,
        )
        self.db.add(math_submission)
        self.db.flush()
        self.db.add_all([
            SubmissionReview(submission_id=math_submission.id, status="pending"),
            Essay(
                student_id=self.student.id, question_id=essay_question.id,
                text="A sufficiently long essay response.", scores_json="{}",
                grammar_issues_json="[]", overall_comment="已完成",
            ),
        ])
        self.db.commit()

        result = list_assignments(
            include_questions=False,
            include_submission_status=True,
            include_pending_count=True,
            include_chat_questions=False,
            created_on=None,
            db=self.db,
            current=self.student,
        )
        item = next(row for row in result["items"] if row["id"] == assignment.id)
        self.assertEqual(item["question_count"], 2)
        self.assertEqual(item["submitted_count"], 2)
        self.assertEqual(
            set(item["submitted_question_ids"]),
            {math_question.id, essay_question.id},
        )
        self.assertEqual(item["pending_count"], 1)
        self.assertEqual(item["pending_question_ids"], [math_question.id])

    def test_shared_mixed_subject_assignment_uses_class_subject_question_scope(self):
        from app.services.teacher_scope import (
            teacher_assignment_class_pairs,
            teacher_assignment_question_ids,
            teacher_assignment_question_student_pairs,
        )

        physics_teacher = User(name="共享作业物理教师", role="teacher")
        owner = User(name="共享作业发布教师", role="teacher")
        completed_student = User(
            name="数学已完成学生", role="student", student_no="mixed-math-done",
        )
        missing_student = User(
            name="数学未完成学生", role="student", student_no="mixed-math-missing",
        )
        physics_student = User(
            name="物理班学生", role="student", student_no="mixed-physics-student",
        )
        self.db.add_all([
            physics_teacher, owner, completed_student, missing_student,
            physics_student,
        ])
        self.db.flush()
        math_class = Classroom(name="共享混合数学班", created_by=owner.id)
        physics_class = Classroom(name="共享混合物理班", created_by=owner.id)
        self.db.add_all([math_class, physics_class])
        self.db.flush()
        self.db.add_all([
            TeacherSubject(teacher_id=owner.id, subject="math"),
            TeacherSubject(teacher_id=owner.id, subject="physics"),
            TeacherSubject(teacher_id=physics_teacher.id, subject="physics"),
            ClassroomTeacherSubject(
                classroom_id=math_class.id, teacher_id=self.teacher.id, subject="math",
            ),
            ClassroomTeacherSubject(
                classroom_id=math_class.id, teacher_id=physics_teacher.id, subject="physics",
            ),
            ClassroomTeacherSubject(
                classroom_id=physics_class.id, teacher_id=physics_teacher.id, subject="physics",
            ),
            # 发布者在两个接收班级都负责这份混合学科作业中的全部学科。
            ClassroomTeacherSubject(
                classroom_id=math_class.id, teacher_id=owner.id, subject="math",
            ),
            ClassroomTeacherSubject(
                classroom_id=math_class.id, teacher_id=owner.id, subject="physics",
            ),
            ClassroomTeacherSubject(
                classroom_id=physics_class.id, teacher_id=owner.id, subject="math",
            ),
            ClassroomTeacherSubject(
                classroom_id=physics_class.id, teacher_id=owner.id, subject="physics",
            ),
            ClassroomMember(classroom_id=math_class.id, student_id=completed_student.id),
            ClassroomMember(classroom_id=math_class.id, student_id=missing_student.id),
            ClassroomMember(classroom_id=physics_class.id, student_id=physics_student.id),
        ])
        assignment = Assignment(title="混合学科共享作业", created_by=owner.id)
        self.db.add(assignment)
        self.db.flush()
        math_question = Question(
            assignment_id=assignment.id, subject="math", knowledge_point="方程",
            stem="数学题干", standard_answer="数学参考答案不得外露", order_num=1,
        )
        physics_question = Question(
            assignment_id=assignment.id, subject="physics", knowledge_point="力学",
            stem="物理题干", standard_answer="物理参考答案不得外露", order_num=2,
        )
        self.db.add_all([
            math_question, physics_question,
            AssignmentClass(assignment_id=assignment.id, classroom_id=math_class.id),
            AssignmentClass(assignment_id=assignment.id, classroom_id=physics_class.id),
        ])
        self.db.flush()
        self.db.add(Submission(
            student_id=completed_student.id, question_id=math_question.id,
        ))
        self.db.commit()

        visible_question_ids = teacher_assignment_question_ids(
            self.db, self.teacher, [assignment.id],
        )
        visible_class_pairs = {
            (row.assignment_id, row.classroom_id)
            for row in teacher_assignment_class_pairs(
                self.db, self.teacher, [assignment.id],
            ).all()
        }
        self.assertEqual(
            {row[0] for row in visible_question_ids.all()},
            {math_question.id},
        )
        self.assertEqual(visible_class_pairs, {(assignment.id, math_class.id)})

        assignment_item = _teacher_assignments_out(
            [assignment], self.db, self.teacher,
            submission_ids=teacher_submission_ids(self.db, self.teacher),
            essay_ids=teacher_essay_ids(self.db, self.teacher),
            question_ids=visible_question_ids,
            visible_class_pairs=visible_class_pairs,
        )[0]
        self.assertEqual([question.id for question in assignment_item.questions], [math_question.id])
        self.assertEqual(
            assignment_item.questions[0].standard_answer,
            "数学参考答案不得外露",
        )
        self.assertEqual(assignment_item.class_ids, [math_class.id])

        status_tool = next(
            tool for tool in build_teacher_tools(self.db, self.teacher)
            if tool.name == "get_assignment_status"
        )
        status_text = status_tool.invoke({"assignment_hint": assignment.title})
        self.assertIn("共 1 道题，班级 2 名学生", status_text)
        self.assertIn(completed_student.name, status_text)
        self.assertIn(missing_student.name, status_text)
        self.assertNotIn(physics_student.name, status_text)

        self.assertEqual(
            remind_assignment(assignment.id, self.db, self.teacher),
            {"reminded_count": 1},
        )
        notified_ids = {
            row[0] for row in self.db.query(Notification.user_id).filter_by(
                type="teacher_reminder",
            ).all()
        }
        self.assertEqual(notified_ids, {missing_student.id})

    def test_low_score_suggestions_use_latest_approved_submission_per_student_question(self):
        from app.services.suggestions import build_teaching_suggestions

        peer = User(name="成绩建议同班学生", role="student", student_no="agent-score-peer")
        self.db.add(peer)
        self.db.flush()
        retry_assignment = Assignment(
            title="多次提交不应拉低平均分", created_by=self.teacher.id,
        )
        pending_assignment = Assignment(
            title="待审核成绩不应进入平均分", created_by=self.teacher.id,
        )
        genuinely_low_assignment = Assignment(
            title="真实低分作业仍应提示", created_by=self.teacher.id,
        )
        self.db.add_all([retry_assignment, pending_assignment, genuinely_low_assignment])
        self.db.flush()
        retry_question = Question(
            assignment_id=retry_assignment.id, subject="math",
            knowledge_point="复习", stem="求 x",
        )
        pending_question = Question(
            assignment_id=pending_assignment.id, subject="math",
            knowledge_point="复习", stem="求 y",
        )
        low_question = Question(
            assignment_id=genuinely_low_assignment.id, subject="math",
            knowledge_point="复习", stem="求 z",
        )
        self.db.add_all([retry_question, pending_question, low_question])
        self.db.flush()

        scores = []
        start = datetime(2026, 1, 1)
        for attempt in range(3):
            old_attempt = Submission(
                student_id=self.student.id,
                question_id=retry_question.id,
                status="graded",
                submitted_at=start + timedelta(days=attempt),
            )
            self.db.add(old_attempt)
            self.db.flush()
            scores.append(SubmissionScore(submission_id=old_attempt.id, ai_score=0.0))

        retry_latest = Submission(
            student_id=self.student.id, question_id=retry_question.id,
            status="graded", submitted_at=start + timedelta(days=3),
        )
        retry_peer = Submission(
            student_id=peer.id, question_id=retry_question.id,
            status="graded", submitted_at=start + timedelta(days=4),
        )
        pending_peer = Submission(
            student_id=peer.id, question_id=pending_question.id,
            status="graded", submitted_at=start + timedelta(days=5),
        )
        approved_single = Submission(
            student_id=self.student.id, question_id=pending_question.id,
            status="graded", submitted_at=start + timedelta(days=6),
        )
        low_student = Submission(
            student_id=self.student.id, question_id=low_question.id,
            status="graded", submitted_at=start + timedelta(days=7),
        )
        low_peer = Submission(
            student_id=peer.id, question_id=low_question.id,
            status="graded", submitted_at=start + timedelta(days=8),
        )
        self.db.add_all([
            retry_latest, retry_peer, pending_peer, approved_single, low_student, low_peer,
        ])
        self.db.flush()
        scores.extend([
            SubmissionScore(submission_id=retry_latest.id, ai_score=100.0),
            SubmissionScore(submission_id=retry_peer.id, ai_score=100.0),
            SubmissionScore(submission_id=pending_peer.id, ai_score=0.0),
            SubmissionScore(submission_id=approved_single.id, ai_score=100.0),
            SubmissionScore(submission_id=low_student.id, ai_score=20.0),
            SubmissionScore(submission_id=low_peer.id, ai_score=30.0),
            SubmissionReview(submission_id=pending_peer.id, status="pending"),
        ])
        self.db.add_all(scores)
        self.db.commit()

        assignment_ids = [
            retry_assignment.id, pending_assignment.id, genuinely_low_assignment.id,
        ]
        submission_ids = self.db.query(Submission.id).join(
            Question, Question.id == Submission.question_id,
        ).filter(Question.assignment_id.in_(assignment_ids))
        with self.assertNoLogs("app.services.suggestions", level="ERROR"):
            suggestions = build_teaching_suggestions(self.db, precomputed_stats={
                "repair_rate": {"knowledge_points": []},
                "knowledge_points": [],
                "top_questions": [],
                "assignment_ids": assignment_ids,
                "student_ids": [self.student.id, peer.id],
                "submission_ids": submission_ids,
            })
        low_score_titles = [
            item["title"] for item in suggestions if item["kind"] == "low_score"
        ]
        self.assertEqual(low_score_titles, ["巩固练习：真实低分作业仍应提示"])

    def test_mixed_subject_score_report_keeps_subject_averages_separate(self):
        from app.services.scoring import student_score_report

        assignment = Assignment(title="跨学科成绩报告", created_by=self.teacher.id)
        self.db.add(assignment)
        self.db.flush()
        math_question = Question(
            assignment_id=assignment.id, subject="math",
            knowledge_point="方程", stem="求 x",
        )
        english_question = Question(
            assignment_id=assignment.id, subject="english",
            knowledge_point="语法", stem="Choose the verb",
        )
        self.db.add_all([math_question, english_question])
        self.db.flush()
        math_submission = Submission(
            student_id=self.student.id, question_id=math_question.id, status="graded",
        )
        english_submission = Submission(
            student_id=self.student.id, question_id=english_question.id, status="graded",
        )
        self.db.add_all([math_submission, english_submission])
        self.db.flush()
        self.db.add_all([
            SubmissionScore(submission_id=math_submission.id, ai_score=40.0),
            SubmissionScore(submission_id=english_submission.id, ai_score=10.0),
        ])
        self.db.commit()

        report = student_score_report(self.db, self.student)
        self.assertEqual(len(report["items"]), 1)
        item = report["items"][0]
        self.assertEqual(item["subject"], "mixed")
        self.assertEqual(item["subjects"], ["english", "math"])
        self.assertEqual((item["score"], item["max_score"], item["rate"]), (50.0, 100.0, 0.5))
        by_subject = {row["subject"]: row for row in report["subjects"]}
        self.assertEqual(by_subject["math"]["avg_rate"], 0.8)
        self.assertEqual(by_subject["english"]["avg_rate"], 0.2)
        self.assertEqual(report["overall_avg_rate"], 0.5)

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
