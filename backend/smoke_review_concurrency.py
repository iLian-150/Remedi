"""Review approval concurrency regressions: python smoke_review_concurrency.py."""
import faulthandler
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Assignment,
    Notification,
    Question,
    Submission,
    SubmissionReview,
    TeacherSubject,
    User,
)
from app.routers import teacher as teacher_router
from app.services import reviews as review_service


class ReviewApprovalConcurrencyTests(unittest.TestCase):
    def setUp(self):
        faulthandler.dump_traceback_later(15, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.temporary = tempfile.TemporaryDirectory(prefix="remedi-review-")
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(self.temporary.name) / 'reviews.sqlite'}",
            connect_args={"check_same_thread": False, "timeout": 5},
            future=True,
        )
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as db:
            self.student = User(name="审核学生", role="student")
            self.teacher = User(name="审核老师", role="teacher")
            db.add_all([self.student, self.teacher])
            db.flush()
            db.add(TeacherSubject(teacher_id=self.teacher.id, subject="math"))
            assignment = Assignment(title="审核并发测试", created_by=self.teacher.id)
            db.add(assignment)
            db.flush()
            question = Question(
                assignment_id=assignment.id,
                subject="math",
                knowledge_point="一次函数",
                stem="求 y=2x+1 在 x=1 时的值",
            )
            db.add(question)
            db.flush()
            submission = Submission(
                student_id=self.student.id,
                question_id=question.id,
            )
            db.add(submission)
            db.flush()
            db.add(SubmissionReview(
                submission_id=submission.id,
                status=review_service.PENDING,
            ))
            db.commit()
            self.student_id = self.student.id
            self.teacher_id = self.teacher.id
            self.submission_id = submission.id

    def _run_concurrent(self, approve):
        barrier = threading.Barrier(2)
        thread_state = threading.local()

        def wait_until_both_attempt_transition(
            _connection, _cursor, statement, _parameters, _context, _executemany,
        ):
            sql = statement.lower()
            if sql.lstrip().startswith("update submission_reviews") and not getattr(
                thread_state, "waited", False,
            ):
                thread_state.waited = True
                barrier.wait(timeout=5)

        event.listen(self.engine, "before_cursor_execute", wait_until_both_attempt_transition)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(approve) for _ in range(2)]
                return [future.result(timeout=8) for future in futures]
        finally:
            event.remove(self.engine, "before_cursor_execute", wait_until_both_attempt_transition)

    def _approve_one(self):
        with Session(self.engine) as db:
            submission = db.get(Submission, self.submission_id)
            teacher = db.get(User, self.teacher_id)
            row = review_service.approve_submission(db, submission, teacher)
            return row.status

    def _approve_single_endpoint_one(self):
        with Session(self.engine) as db:
            teacher = db.get(User, self.teacher_id)
            with (
                patch.object(teacher_router, "_require_teacher_assignment"),
                patch.object(teacher_router.scoring_svc, "finalize_on_approve"),
                patch.object(teacher_router.review_svc, "refresh_assignment_review"),
            ):
                return teacher_router.review_approve(
                    self.submission_id, None, db, teacher,
                )

    def _approve_all_one(self):
        with Session(self.engine) as db:
            submission = db.get(Submission, self.submission_id)
            teacher = db.get(User, self.teacher_id)
            approved_ids = review_service.approve_submissions(db, [submission], teacher)
            db.commit()
            return approved_ids

    def _approve_all_endpoint_one(self):
        with Session(self.engine) as db:
            teacher = db.get(User, self.teacher_id)
            with patch.object(teacher_router.scoring_svc, "finalize_on_approve_many"):
                return teacher_router.reviews_approve_all(db, teacher)

    def _assert_one_approval_notification(self):
        with Session(self.engine) as db:
            count = db.query(Notification).filter(
                Notification.user_id == self.student_id,
                Notification.type == "review_approved",
                Notification.related_submission_id == self.submission_id,
            ).count()
            self.assertEqual(count, 1)
            self.assertEqual(
                db.get(SubmissionReview, self.submission_id).status,
                review_service.APPROVED,
            )

    def test_parallel_single_approval_sends_only_one_notification(self):
        self._run_concurrent(self._approve_one)
        self._assert_one_approval_notification()

    def test_parallel_single_approval_endpoint_sends_only_one_notification(self):
        results = self._run_concurrent(self._approve_single_endpoint_one)
        self.assertTrue(all(result["review_status"] == review_service.APPROVED for result in results))
        self._assert_one_approval_notification()

    def test_parallel_approve_all_sends_only_one_notification(self):
        results = self._run_concurrent(self._approve_all_one)
        self.assertEqual(sorted(len(result) for result in results), [0, 1])
        self._assert_one_approval_notification()

    def test_parallel_approve_all_endpoint_reports_actual_transitions(self):
        results = self._run_concurrent(self._approve_all_endpoint_one)
        self.assertEqual(sorted(result["approved_count"] for result in results), [0, 1])
        self._assert_one_approval_notification()

    def test_parallel_pending_review_creation_is_idempotent(self):
        with Session(self.engine) as db:
            db.query(SubmissionReview).filter_by(
                submission_id=self.submission_id,
            ).delete()
            db.commit()

        barrier = threading.Barrier(2)
        thread_state = threading.local()

        def wait_until_both_observe_empty_queue(
            _connection, _cursor, statement, _parameters, _context, _executemany,
        ):
            sql = statement.lower()
            if "from submission_reviews" in sql and "submission_reviews.submission_id in" in sql and not getattr(
                thread_state, "waited", False,
            ):
                thread_state.waited = True
                barrier.wait(timeout=5)

        def create_pending_review():
            with Session(self.engine) as db:
                submission = db.get(Submission, self.submission_id)
                try:
                    review_service.create_pending_reviews(db, [submission])
                except Exception as exc:
                    db.rollback()
                    return type(exc).__name__
                return "created"

        event.listen(self.engine, "after_cursor_execute", wait_until_both_observe_empty_queue)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=8) for future in [
                    pool.submit(create_pending_review),
                    pool.submit(create_pending_review),
                ]]
        finally:
            event.remove(self.engine, "after_cursor_execute", wait_until_both_observe_empty_queue)

        self.assertEqual(results, ["created", "created"])
        with Session(self.engine) as db:
            rows = db.query(SubmissionReview).filter_by(
                submission_id=self.submission_id,
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, review_service.PENDING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
