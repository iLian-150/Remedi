"""明日讲评重点、已讲记录和变式练习的隔离回归。"""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import require_teacher
from app.database import Base, get_db
from app.models import (Assignment, AssignmentClass, Classroom, ClassroomMember, ClassroomTeacherSubject,
                        Error, Question, Submission, SubmissionReview, TeacherSubject, TeacherTeachingFocus, User)
from app.routers import teacher_teaching
from app.services import teaching_plan, variant_gen


class TeachingPlanTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.teacher = User(id=1, name="数学老师", role="teacher")
        self.db.add_all([self.teacher, User(id=2, name="其他老师", role="teacher")])
        self.db.add_all([User(id=i, name=f"学生{i}", role="student") for i in range(3, 8)])
        self.db.flush()
        self.db.add_all([TeacherSubject(teacher_id=1, subject="math"), TeacherSubject(teacher_id=1, subject="chinese")])
        self.db.add_all([Classroom(id=i, name=f"班级{i}", created_by=i) for i in (1, 2)])
        self.db.add(Assignment(id=1, title="跨班作业", created_by=2))
        self.db.flush()
        self.db.add_all([ClassroomTeacherSubject(classroom_id=1, teacher_id=1, subject=s) for s in ("math", "chinese")])
        self.db.add(ClassroomTeacherSubject(classroom_id=2, teacher_id=2, subject="math"))
        self.db.add_all([ClassroomMember(classroom_id=1, student_id=i) for i in (3, 4, 6, 7)])
        self.db.add(ClassroomMember(classroom_id=2, student_id=5))
        self.db.add_all([AssignmentClass(assignment_id=1, classroom_id=i) for i in (1, 2)])
        self.db.commit()
        self.now = datetime(2026, 11, 10, 12)
        app = FastAPI()
        app.include_router(teacher_teaching.router)
        def session():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        app.dependency_overrides[require_teacher] = lambda: self.teacher
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def attempt(self, kp="一元一次方程", student=3, *, wrong=True, steps=1, pending=False,
                when=None, subject="math", question_kp=None):
        when = when or self.now - timedelta(days=1)
        question = Question(assignment_id=1, subject=subject, knowledge_point=question_kp or kp, stem="题干")
        self.db.add(question)
        self.db.flush()
        submission = Submission(student_id=student, question_id=question.id, status="graded", submitted_at=when)
        self.db.add(submission)
        self.db.flush()
        if pending:
            self.db.add(SubmissionReview(submission_id=submission.id, status="pending"))
        if wrong:
            for _ in range(steps):
                self.db.add(Error(submission_id=submission.id, knowledge_point=kp,
                                  error_type="概念混淆", confidence=1, created_at=when))
        self.db.commit()
        return submission

    def plan(self):
        return teaching_plan.build_teaching_plan(self.db, self.teacher, now=self.now)

    def test_top_three_common_points_deduplicate_steps_and_include_correct_attempts(self):
        self.attempt(steps=5)
        self.attempt(student=4)
        self.attempt(student=6, wrong=False)
        self.attempt(student=7, wrong=False)
        for kp in ("函数", "几何", "概率"):
            self.attempt(kp=kp)
            self.attempt(kp=kp, student=4)
        self.attempt(kp="个人难点", steps=10)
        result = self.plan()["topics"]
        self.assertEqual(len(result), 3)
        self.assertNotIn("个人难点", [r["knowledge_point"] for r in result])
        # 四个点都涉及两人，错误率更高的三个先展示；不会拿错误步骤数除提交数。
        self.assertTrue(all(r["error_rate"] == 1 for r in result))
        stats = teaching_plan.knowledge_point_stats(self.db, self.teacher)
        algebra = next(r for r in stats if r.knowledge_point == "一元一次方程")
        self.assertEqual((algebra.attempts, algebra.errors, algebra.student_count), (4, 2, 2))

    def test_scope_pending_and_subject_separation(self):
        self.attempt(kp="私有点", student=5)
        self.attempt(kp="私有点", student=3)
        self.attempt(kp="待审核", student=3, pending=True)
        self.attempt(kp="待审核", student=4, pending=True)
        self.attempt(kp="同名", student=3, subject="math")
        self.attempt(kp="同名", student=4, subject="chinese")
        self.assertEqual(self.plan()["topics"], [])
        denied = self.client.post("/api/teacher/teaching-plan/exercise", json={"subject":"math", "knowledge_point":"待审核"})
        self.assertEqual(denied.status_code, 404)
        denied = self.client.post("/api/teacher/teaching-plan/taught", json={"subject":"math", "knowledge_point":"不存在"})
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.db.query(TeacherTeachingFocus).count(), 0)

    def test_follow_up_counts_only_this_week_after_real_teaching_not_late_old_grading(self):
        taught = self.now - timedelta(days=2)
        self.db.add(TeacherTeachingFocus(teacher_id=1, subject="math", knowledge_point="函数", taught_at=taught))
        self.db.add(TeacherTeachingFocus(teacher_id=2, subject="math", knowledge_point="其他老师的点", taught_at=self.now))
        self.db.commit()
        self.attempt(kp="函数", when=self.now - timedelta(hours=1), steps=3)
        self.attempt(kp="函数", when=self.now - timedelta(minutes=30))
        old = self.attempt(kp="函数", student=4, when=taught - timedelta(hours=1))
        self.db.query(Error).filter(Error.submission_id == old.id).update({Error.created_at: self.now})
        self.attempt(kp="函数", student=5, when=self.now)
        self.db.commit()
        result = self.plan()["follow_up"]
        self.assertEqual(result["knowledge_point"], "函数")
        self.assertEqual(result["student_count"], 1)
        self.db.query(TeacherTeachingFocus).filter_by(teacher_id=1).update({TeacherTeachingFocus.taught_at: self.now})
        self.db.commit()
        self.assertEqual(self.plan()["follow_up"]["student_count"], 0)

    def test_taught_record_persists_and_same_day_retries_do_not_reset_time(self):
        self.attempt()
        self.attempt(student=4)
        payload = {"subject":"math", "knowledge_point":"一元一次方程"}
        first = self.client.post("/api/teacher/teaching-plan/taught", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post("/api/teacher/teaching-plan/taught", json=payload)
        self.assertEqual(first.json()["follow_up"]["taught_at"], second.json()["follow_up"]["taught_at"])
        loaded = self.client.get("/api/teacher/teaching-plan")
        self.assertEqual(loaded.json()["topics"][0]["taught_at"], first.json()["follow_up"]["taught_at"])
        self.assertEqual(self.db.query(TeacherTeachingFocus).count(), 1)

    def test_exercise_uses_real_template_and_does_not_mark_taught(self):
        self.attempt()
        with patch.object(variant_gen, "get_provider", side_effect=AssertionError("template should not call model")):
            response = self.client.post("/api/teacher/teaching-plan/exercise", json={"subject":"math", "knowledge_point":"一元一次方程"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(variant_gen.verify_chain(data["prompt"], data["standard_steps"], data["answer"]))
        self.assertIsNone(self.client.get("/api/teacher/teaching-plan").json()["follow_up"])

    def test_other_subject_generation_and_safe_failure_are_retryable(self):
        self.attempt(kp="人物形象", subject="chinese")
        provider = Mock()
        provider._chat.return_value = json.dumps({"prompt":"阅读材料：张师傅耐心修鞋。分析人物特点。", "standard_steps":["提取耐心修鞋的细节"], "answer":"张师傅做事耐心。"})
        provider._extract_json.side_effect = json.loads
        payload = {"subject":"chinese", "knowledge_point":"人物形象"}
        with patch.object(variant_gen, "get_provider", return_value=provider):
            response = self.client.post("/api/teacher/teaching-plan/exercise", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('"subject": "chinese"', provider._chat.call_args.args[1])
        provider._chat.side_effect = RuntimeError("private upstream details")
        with patch.object(variant_gen, "get_provider", return_value=provider):
            failed = self.client.post("/api/teacher/teaching-plan/exercise", json=payload)
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("private", failed.text)

    def test_week_boundary_uses_app_timezone(self):
        from zoneinfo import ZoneInfo
        from datetime import timezone
        moment = datetime(2026, 11, 8, 18, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        with patch.object(teaching_plan.settings, "APP_TIMEZONE", "Asia/Shanghai"):
            start = teaching_plan.week_start_for_database(moment)
            first = datetime(2026, 11, 9, 17, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            second = datetime(2026, 11, 10, 10, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            self.assertTrue(teaching_plan.same_teaching_day(first, second))
        expected = datetime(2026, 11, 9, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone().replace(tzinfo=None)
        self.assertEqual(start, expected)


if __name__ == "__main__":
    unittest.main()
