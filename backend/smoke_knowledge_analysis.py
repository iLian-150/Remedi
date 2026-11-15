"""Knowledge point counts, scope and correction state using local fixtures."""
from datetime import datetime
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Assignment, Base, Correction, Error, Question, Step, Submission,
    SubmissionReview, User, Verification,
)
from app.routers import student
from app.services.knowledge_analysis import student_knowledge_analysis


class KnowledgeAnalysisTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = Session(engine, expire_on_commit=False)
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(name="画像样例", role="student", student_no="profile-sample")
        self.assignment = Assignment(title="学情样例")
        self.db.add_all([self.user, self.assignment])
        self.db.flush()
        app = FastAPI()
        app.include_router(student.router)
        app.dependency_overrides[student.get_db] = lambda: self.db
        app.dependency_overrides[student.require_student] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def question(self, subject="math", point="方程"):
        question = Question(
            assignment_id=self.assignment.id, subject=subject, knowledge_point=point,
            stem="学情样例题目",
        )
        self.db.add(question)
        self.db.flush()
        return question

    def submission(self, question, status="graded"):
        submission = Submission(student_id=self.user.id, question_id=question.id, status=status)
        self.db.add(submission)
        self.db.flush()
        return submission

    def error(self, submission, day=1, error_type="概念混淆", step=None):
        error = Error(
            submission_id=submission.id, knowledge_point=submission.question.knowledge_point,
            error_type=error_type, confidence=0.8, step=step, created_at=datetime(2026, 1, day),
        )
        self.db.add(error)
        self.db.flush()
        return error

    def correct(self, error):
        self.db.add(Correction(
            error_id=error.id, student_id=self.user.id, content="已订正的步骤", is_correct=True,
        ))

    def verify(self, error, day):
        self.db.add(Verification(
            student_id=self.user.id, knowledge_point=error.knowledge_point,
            source_error_id=error.id, variant_json="{}", status="passed",
            completed_at=datetime(2026, 1, day),
        ))

    def analysis(self, **scope):
        self.db.flush()
        result, _ = student_knowledge_analysis(self.db, self.user.id, **scope)
        points = {(p["subject"], p["knowledge_point"]): p for p in result["points"]}
        return result, points

    def get(self, path):
        self.db.commit()
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_counts_distinct_questions_and_respects_both_profile_scopes(self):
        math = self.question()
        first = self.submission(math)
        retry = self.submission(math, status="submitted")
        self.error(first)
        self.error(first, error_type="计算失误")
        self.error(retry)
        correct_math = self.submission(self.question())
        pending_math = self.submission(self.question())
        self.error(pending_math, day=2)
        self.db.add(SubmissionReview(submission_id=pending_math.id, status="pending"))
        self.error(self.submission(self.question("physics")))
        self.submission(self.question(point=""))
        self.submission(self.question(point="尚未批改"), status="deferred")

        result, points = self.analysis(visible_only=True)
        self.assertEqual(set(points), {("math", "方程"), ("physics", "方程"), ("math", "")})
        self.assertEqual(result["graded_question_count"], 4)
        self.assertEqual(result["wrong_question_count"], 2)
        point = points[("math", "方程")]
        self.assertEqual((point["question_count"], point["attempts"], point["wrong_question_count"]), (2, 3, 1))
        self.assertEqual(point["status"], "pending")
        self.assertTrue(all(pattern["question_count"] == 1 for pattern in point["patterns"]))
        self.assertEqual(points[("math", "")]["status"], "unclassified")

        submissions = self.db.query(Submission.id).filter(Submission.id.in_(
            [first.id, retry.id, correct_math.id, pending_math.id],
        ))
        _, teacher_points = self.analysis(assignment_ids=[self.assignment.id], submission_ids=submissions)
        self.assertEqual(set(teacher_points), {("math", "方程")})
        self.assertEqual(teacher_points[("math", "方程")]["status"], "stubborn")
        self.assertEqual(teacher_points[("math", "方程")]["patterns"][0]["pending_question_count"], 2)

    def test_new_error_reopens_verification_and_endpoint_returns_link_target(self):
        first = self.error(self.submission(self.question()))
        self.correct(first)
        self.verify(first, day=2)
        self.assertEqual(self.analysis()[1][("math", "方程")]["status"], "fixed")

        newer = self.error(self.submission(self.question()), day=3)
        self.correct(newer)
        other_subject = self.error(self.submission(self.question("physics")), day=3)
        self.correct(other_subject)
        self.correct(self.error(self.submission(self.question(point=""))))
        self.db.add(Verification(
            student_id=self.user.id, knowledge_point="其他知识点", source_error_id=newer.id,
            variant_json="{}", status="passed", completed_at=datetime(2026, 1, 4),
        ))
        profile = self.get("/api/student/profile")
        analysis = profile["knowledge_analysis"]
        self.assertEqual(analysis["corrected_count"], 4)
        points = {point["subject"]: point for point in analysis["points"] if point["knowledge_point"]}
        self.assertEqual(points["math"]["status"], "awaiting_verify")
        self.assertEqual(points["physics"]["status"], "corrected")
        self.assertTrue(all(item["corrected"] for item in profile["recent_errors"]))
        self.assertEqual(self.get("/api/student/corrections/awaiting-verification-knowledge-points"), [
            {"subject": "math", "knowledge_point": "方程", "source_error_id": newer.id},
        ])

        self.verify(newer, day=4)
        self.assertEqual(self.analysis()[1][("math", "方程")]["status"], "fixed")
        self.assertEqual(self.get("/api/student/corrections/awaiting-verification-knowledge-points"), [])

    def test_unreadable_steps_are_kept_out_of_error_patterns(self):
        submission = self.submission(self.question("chinese", "错别字"))
        step = Step(submission_id=submission.id, seq=1, text="字迹不清", status="unparseable")
        self.error(submission, step=step)
        result, points = self.analysis()
        self.assertEqual(result["wrong_question_count"], 0)
        self.assertEqual(result["error_types"], [{"error_type": "无法解析", "count": 1}])
        point = points[("chinese", "错别字")]
        self.assertEqual(point["patterns"], [])
        self.assertEqual((point["status"], point["review_count"]), ("needs_review", 1))


if __name__ == "__main__":
    unittest.main()
