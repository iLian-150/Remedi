"""隔离验证整份作业图片暂存、文本暂存和提交。"""
from pathlib import Path
from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock, patch
from sqlalchemy import inspect, text

from app import database
from app.auth import require_student
from app.models import AssignmentGradingAnswer, AssignmentGradingCheckpoint, AssignmentGradingJob, ClassroomMember, Question, Submission, User
from app.routers import student, student_assignment_image
from app.services import assignment_grading
import smoke_diagram_jobs as fixtures


class AssignmentAnswerUploadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DiagramJobsTest(methodName="runTest")
        self.fixture.setUp()
        self.tmp = self.fixture.tmp
        self.sessions = self.fixture.sessions
        self.app = self.fixture.app
        self.client = self.fixture.client
        self.app.include_router(student_assignment_image.router)
        self.draft_path = Path(self.tmp.name) / "private-drafts"
        self.draft_setting = patch.object(student.settings, "ASSIGNMENT_DRAFT_DIR", str(self.draft_path))
        self.draft_setting.start()
        job = self.fixture.job()
        response = self.fixture.publish(job)
        self.assertEqual(response.status_code, 200, response.text)
        self.assignment_id = response.json()["id"]
        self.question_id = response.json()["questions"][0]["id"]
        self.answer_url = f"/api/student/assignments/{self.assignment_id}/answers/{self.question_id}"

    def tearDown(self):
        self.draft_setting.stop()
        self.fixture.tearDown()

    def test_image_is_persisted_then_assignment_can_be_submitted(self):
        image = b"\xff\xd8\xff synthetic answer image"
        response = self.client.put(self.answer_url, files={"file": ("answer.jpg", image, "image/jpeg")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answered_question_ids"], [self.question_id])
        self.assertEqual(response.json()["image_question_ids"], [self.question_id])
        assignment = next(item for item in self.client.get("/api/student/assignments").json()["items"] if item["id"] == self.assignment_id)
        self.assertEqual(assignment["staged_count"], 1)
        self.assertEqual(assignment["grading_status"], "draft")
        image_url = self.answer_url + "/image"
        saved = self.client.get(image_url)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.content, image)
        self.assertEqual(saved.headers["cache-control"], "private, no-store")
        with self.sessions() as db:
            db.add(User(id=4, role="student", name="classmate"))
            db.add(ClassroomMember(student_id=4, classroom_id=1))
            db.commit()
        self.app.dependency_overrides[require_student] = lambda: User(id=4, role="student", name="classmate")
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.app.dependency_overrides[require_student] = lambda: User(id=3, role="student", name="other")
        self.assertEqual(self.client.get(image_url).status_code, 404)
        self.app.dependency_overrides[require_student] = lambda: User(id=2, role="student", name="student")
        with self.sessions() as db:
            answer = db.query(AssignmentGradingAnswer).filter_by(question_id=self.question_id).one()
            self.assertEqual((self.draft_path / answer.image_path).read_bytes(), image)
        with patch.object(student.assignment_grading_svc, "enqueue") as enqueue:
            response = self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "queued")
        enqueue.assert_called_once()

    def test_image_path_cannot_escape_private_directory(self):
        response = self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            answer = db.query(AssignmentGradingAnswer).filter_by(question_id=self.question_id).one()
            answer.image_path = "../outside.jpg"
            db.commit()
        self.assertEqual(self.client.get(self.answer_url + "/image").status_code, 404)

    def test_text_answer_and_out_of_scope_upload(self):
        self.app.dependency_overrides[require_student] = lambda: User(id=3, role="student", name="other")
        response = self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        self.assertEqual(response.status_code, 404)
        self.app.dependency_overrides[require_student] = lambda: User(id=2, role="student", name="student")
        response = self.client.put(self.answer_url, data={"answer_text": "x + 1 = 2\nx = 1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["image_question_ids"], [])
        self.assertEqual(self.client.get(self.answer_url + "/image").status_code, 404)
        with patch.object(student.assignment_grading_svc, "enqueue"):
            response = self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "queued")

    def test_empty_model_result_retries_then_grades_saved_image(self):
        self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        with patch.object(student.assignment_grading_svc, "enqueue"):
            self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        with self.sessions() as db:
            job_id = db.query(AssignmentGradingJob).filter_by(assignment_id=self.assignment_id).one().id
        provider = Mock()
        provider.guess_knowledge_point.return_value = ""
        provider.diagnose_homework_image.side_effect = [
            {"steps": []},
            {"steps": [{"text": "x=1", "result": "correct", "confidence": 0.9}]},
        ]
        with patch.object(assignment_grading, "SessionLocal", self.sessions), \
             patch.object(assignment_grading, "get_provider", return_value=provider), \
             patch("app.agent.subjects.build_subject_context", return_value=""), \
             patch.object(assignment_grading.settings, "UPLOAD_DIR", str(Path(self.tmp.name) / "uploads")):
            assignment_grading._grade_job(job_id)
        with self.sessions() as db:
            self.assertEqual(db.get(AssignmentGradingJob, job_id).status, "completed")
            self.assertEqual(db.query(Submission).count(), 1)
        self.assertEqual(provider.diagnose_homework_image.call_count, 2)

    def test_failed_grading_retries_without_student_session_and_finishes_once(self):
        self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        with patch.object(student.assignment_grading_svc, "enqueue"):
            self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        with self.sessions() as db:
            job_id = db.query(AssignmentGradingJob).filter_by(assignment_id=self.assignment_id).one().id
        provider = Mock()
        provider.guess_knowledge_point.return_value = ""
        provider.diagnose_homework_image.return_value = {"steps": []}
        with patch.object(assignment_grading, "SessionLocal", self.sessions), \
             patch.object(assignment_grading, "get_provider", return_value=provider), \
             patch("app.agent.subjects.build_subject_context", return_value=""):
            assignment_grading._grade_job(job_id)
        status = self.client.get(f"/api/student/assignments/{self.assignment_id}/grading-status").json()
        self.assertEqual(status["status"], "queued")
        self.assertIn("自动重试", status["error"])
        self.assertEqual(status["image_question_ids"], [self.question_id])
        self.assertEqual(self.client.get(self.answer_url + "/image").content, b"image")
        with self.sessions() as db:
            self.assertEqual(db.query(Submission).count(), 0)
        self.assertEqual(provider.diagnose_homework_image.call_count, 2)
        with patch.object(assignment_grading, "SessionLocal", self.sessions):
            self.assertIsNone(assignment_grading._next_ready_job_id())
            assignment_grading._grade_job(job_id)
        self.assertEqual(provider.diagnose_homework_image.call_count, 2)
        with self.sessions() as db:
            job = db.get(AssignmentGradingJob, job_id)
            self.assertEqual(job.retry_count, 1)
            self.assertGreater(job.next_attempt_at, datetime.now())
            job.next_attempt_at = datetime.now() - timedelta(seconds=1)
            db.commit()
        # 后台任务不依赖当前浏览器账号：模拟学生已退出/切换账号。
        self.app.dependency_overrides[require_student] = lambda: User(id=3, role="student", name="other")
        provider.diagnose_homework_image.return_value = {
            "steps": [{"text": "x=1", "result": "correct", "confidence": 0.9}],
        }
        with patch.object(assignment_grading, "SessionLocal", self.sessions), \
             patch.object(assignment_grading, "get_provider", return_value=provider), \
             patch("app.agent.subjects.build_subject_context", return_value=""), \
             patch.object(assignment_grading.settings, "UPLOAD_DIR", str(Path(self.tmp.name) / "uploads")):
            self.assertEqual(assignment_grading._next_ready_job_id(), job_id)
            assignment_grading._grade_job(job_id)
            assignment_grading._grade_job(job_id)
        with self.sessions() as db:
            self.assertEqual(db.get(AssignmentGradingJob, job_id).status, "completed")
            self.assertEqual(db.query(Submission).count(), 1)

    def test_retry_reuses_successful_question_after_later_question_times_out(self):
        self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        with patch.object(student.assignment_grading_svc, "enqueue"):
            self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        with self.sessions() as db:
            job = db.query(AssignmentGradingJob).one()
            job_id = job.id
            first = db.get(Question, self.question_id)
            first.knowledge_point = "已识别知识点"
            second = Question(assignment_id=self.assignment_id, subject="math", stem="求 x", knowledge_point="方程", order_num=2)
            db.add(second)
            db.flush()
            db.add(AssignmentGradingAnswer(job_id=job_id, question_id=second.id, answer_text="x=2"))
            db.commit()
        provider = Mock()
        diagnosis = {"steps": [{"text": "x=1", "result": "correct", "confidence": 0.9}]}
        provider.diagnose_homework_image.return_value = diagnosis
        provider.diagnose_homework_text.side_effect = RuntimeError("timeout")
        with patch.object(assignment_grading, "SessionLocal", self.sessions), \
             patch.object(assignment_grading, "get_provider", return_value=provider), \
             patch("app.agent.subjects.build_subject_context", return_value=""), \
             patch.object(assignment_grading.settings, "UPLOAD_DIR", str(Path(self.tmp.name) / "uploads")):
            assignment_grading._grade_job(job_id)
            with self.sessions() as db:
                self.assertEqual(db.query(AssignmentGradingCheckpoint).count(), 1)
                self.assertEqual(db.query(Submission).count(), 0)
                db.get(AssignmentGradingJob, job_id).next_attempt_at = datetime.now() - timedelta(seconds=1)
                db.commit()
            provider.diagnose_homework_text.side_effect = None
            provider.diagnose_homework_text.return_value = diagnosis
            assignment_grading._grade_job(job_id)
        self.assertEqual(provider.diagnose_homework_image.call_count, 1)
        self.assertEqual(provider.diagnose_homework_text.call_count, 3)
        provider.guess_knowledge_point.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(AssignmentGradingJob, job_id).status, "completed")
            self.assertEqual(db.query(Submission).count(), 2)

    def test_changed_image_invalidates_checkpoint_after_persistence_failure(self):
        self.client.put(self.answer_url, files={"file": ("answer.jpg", b"image", "image/jpeg")})
        with patch.object(student.assignment_grading_svc, "enqueue"):
            self.client.post(f"/api/student/assignments/{self.assignment_id}/submit")
        with self.sessions() as db:
            job_id = db.query(AssignmentGradingJob).one().id
        provider = Mock()
        provider.guess_knowledge_point.return_value = "方程"
        provider.diagnose_homework_image.return_value = {"steps": [{"text": "x=1", "result": "correct", "confidence": 0.9}]}
        with patch.object(assignment_grading, "SessionLocal", self.sessions), \
             patch.object(assignment_grading, "get_provider", return_value=provider), \
             patch("app.agent.subjects.build_subject_context", return_value=""), \
             patch.object(assignment_grading.settings, "UPLOAD_DIR", str(Path(self.tmp.name) / "uploads")):
            with patch.object(assignment_grading.scoring_svc, "persist_ai_score", side_effect=RuntimeError("temporary persistence failure")):
                assignment_grading._grade_job(job_id)
            with self.sessions() as db:
                answer = db.query(AssignmentGradingAnswer).filter_by(job_id=job_id).one()
                (self.draft_path / answer.image_path).write_bytes(b"changed image")
                db.get(AssignmentGradingJob, job_id).next_attempt_at = datetime.now() - timedelta(seconds=1)
                db.commit()
            assignment_grading._grade_job(job_id)
        self.assertEqual(provider.diagnose_homework_image.call_count, 2)
        with self.sessions() as db:
            self.assertEqual(db.get(AssignmentGradingJob, job_id).status, "completed")
            self.assertEqual(db.query(Submission).count(), 1)

    def test_startup_recovers_interrupted_and_failed_jobs(self):
        self.client.put(self.answer_url, data={"answer_text": "x=1"})
        for previous in ("processing", "failed"):
            with self.sessions() as db:
                job = db.query(AssignmentGradingJob).one()
                job.status = previous
                job.next_attempt_at = datetime.now() + timedelta(minutes=5)
                db.commit()
            with patch.object(assignment_grading, "SessionLocal", self.sessions), \
                 patch.object(assignment_grading, "_worker", None), \
                 patch.object(assignment_grading.threading, "Thread"):
                assignment_grading.start_worker()
                self.assertIsNotNone(assignment_grading._next_ready_job_id())

    def test_existing_database_migration_preserves_answers_and_is_idempotent(self):
        self.client.put(self.answer_url, data={"answer_text": "x=1"})
        with self.fixture.engine.begin() as connection:
            connection.execute(text("ALTER TABLE assignment_grading_jobs DROP COLUMN retry_count"))
            connection.execute(text("ALTER TABLE assignment_grading_jobs DROP COLUMN next_attempt_at"))
        with patch.object(database, "engine", self.fixture.engine):
            database.init_db()
            database.init_db()
        columns = {column["name"] for column in inspect(self.fixture.engine).get_columns("assignment_grading_jobs")}
        self.assertTrue({"retry_count", "next_attempt_at"} <= columns)
        with self.sessions() as db:
            self.assertEqual(db.query(AssignmentGradingJob).one().retry_count, 0)
            self.assertEqual(db.query(AssignmentGradingAnswer).one().answer_text, "x=1")


if __name__ == "__main__":
    unittest.main()
