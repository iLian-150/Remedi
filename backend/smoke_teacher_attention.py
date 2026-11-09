"""验证教师关注名单的统计口径、修复状态与授权边界，不依赖模型。"""
from datetime import datetime, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Assignment, Correction, Error, Question, Submission, SubmissionReview, User, Verification
from app.services.teacher_attention import students_needing_attention


class TeacherAttentionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.now = datetime(2026, 11, 10, 12)
        self.db.add_all([User(id=i, name=f"学生{i}", role="student") for i in range(1, 10)])
        self.db.add_all([Assignment(id=i, title=f"作业{i}") for i in (1, 2)])
        self.db.flush()

    def errors(self, student=1, kp="二次函数", count=1, steps=1, days=0, assignment=1, subject="math"):
        errors = []
        for _ in range(count):
            question = Question(assignment_id=assignment, subject=subject, knowledge_point=kp, stem="题目")
            self.db.add(question)
            self.db.flush()
            submission = Submission(student_id=student, question_id=question.id, status="graded")
            self.db.add(submission)
            self.db.flush()
            for _ in range(steps):
                error = Error(submission_id=submission.id, knowledge_point=kp, error_type="概念混淆",
                              confidence=1, created_at=self.now - timedelta(days=days))
                self.db.add(error)
                errors.append(error)
        self.db.flush()
        return errors

    def correction(self, error, correct=True, days=0):
        submission = self.db.get(Submission, error.submission_id)
        self.db.add(Correction(error_id=error.id, student_id=submission.student_id, content="订正",
                               is_correct=correct, submitted_at=self.now - timedelta(days=days)))
        self.db.flush()

    def verification(self, error, status="passed", days=0):
        student_id = self.db.get(Submission, error.submission_id).student_id
        self.db.add(Verification(student_id=student_id, source_error_id=error.id,
                                 knowledge_point=error.knowledge_point, variant_json="{}", status=status,
                                 created_at=self.now - timedelta(days=days),
                                 completed_at=self.now - timedelta(days=days)))
        self.db.flush()

    def attention(self, students=None, assignments=None, submissions=None):
        return students_needing_attention(
            self.db, student_ids=students if students is not None else list(range(1, 10)),
            assignment_ids=assignments if assignments is not None else [1],
            submission_ids=submissions if submissions is not None else self.db.query(Submission.id),
            now=self.now,
        )

    def test_multiple_steps_do_not_inflate_repetition_and_subjects_are_separate(self):
        self.errors(steps=4)
        self.errors(count=2, subject="physics")
        self.assertEqual(self.attention(), [])
        self.errors(count=2)
        result = self.attention()
        self.assertEqual(len(result), 1)
        self.assertIn("二次函数已错3次", result[0]["reason"])

    def test_repaired_removed_but_new_error_or_failed_verification_brings_back(self):
        errors = self.errors(count=3, days=2)
        for error in errors:
            self.correction(error)
        self.assertIn("巩固验证", self.attention()[0]["reason"])
        self.verification(errors[-1], days=1)
        self.assertEqual(self.attention(), [])
        self.verification(errors[-1], status="failed")
        self.assertEqual(len(self.attention()), 1)
        self.verification(errors[-1])
        self.assertEqual(self.attention(), [])
        self.errors()
        self.assertIn("已错4次", self.attention()[0]["reason"])

    def test_latest_correction_wins_and_overdue_uses_oldest_unresolved(self):
        error = self.errors(days=10)[0]
        self.assertIn("10天未完成订正", self.attention()[0]["reason"])
        self.correction(error, days=1)
        self.assertEqual(self.attention(), [])
        self.correction(error, correct=False)
        self.assertEqual(len(self.attention()), 1)
        self.correction(error, correct=None)
        self.assertEqual(len(self.attention()), 1)
        self.errors(student=2, days=6)
        self.assertNotIn(2, [row["id"] for row in self.attention()])

    def test_authorization_and_pending_review_never_leak(self):
        self.errors(count=3, student=1)
        self.errors(count=3, student=2, assignment=2)
        private = self.errors(count=3, student=3)
        allowed = self.db.query(Submission.id).filter(Submission.student_id == 1)
        self.assertEqual([x["id"] for x in self.attention(students=[1, 2, 3], submissions=allowed)], [1])
        self.assertEqual(self.attention(students=[]), [])
        self.assertEqual(self.attention(assignments=[]), [])
        self.assertEqual(self.attention(submissions=[]), [])
        self.assertEqual(self.attention(students=[2]), [])
        for error in private:
            self.db.add(SubmissionReview(submission_id=error.submission_id, status="pending"))
        self.db.flush()
        self.assertEqual(self.attention(students=[3]), [])

    def test_low_repair_requires_three_points_and_favors_lowest_rate(self):
        for student in (1, 2):
            for kp in ("函数", "方程", "几何"):
                error = self.errors(student=student, kp=kp)[0]
                if student == 2 and kp == "函数":
                    self.correction(error)
                    self.verification(error)
        self.errors(student=3, count=2)
        result = self.attention()
        self.assertEqual([r["id"] for r in result], [1])
        self.assertIn("3个出错知识点仅修复0个", result[0]["reason"])

    def test_verification_from_other_subject_or_unauthorized_source_does_not_repair(self):
        math = self.errors(count=3, days=2)
        for error in math:
            self.correction(error)
        physics = self.errors(subject="physics", days=2)[0]
        self.verification(physics)
        self.assertIn("巩固验证", self.attention()[0]["reason"])
        outside = self.errors(assignment=2, days=2)[0]
        self.verification(outside)
        self.assertIn("巩固验证", self.attention()[0]["reason"])
        self.verification(math[-1], days=3)
        self.assertIn("巩固验证", self.attention()[0]["reason"])

    def test_repeated_first_deduplicated_capped_and_ties_stable(self):
        for student in range(1, 8):
            self.errors(student=student, count=3, days=10)
        self.errors(student=8, count=4)
        rows = self.attention()
        self.assertEqual([row["id"] for row in rows], [8, 1, 2, 3, 4])
        self.assertEqual(len({r["id"] for r in rows}), 5)


if __name__ == "__main__":
    unittest.main()
