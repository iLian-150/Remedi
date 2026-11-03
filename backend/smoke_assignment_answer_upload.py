"""隔离验证整份作业图片暂存、文本暂存和提交。"""
from pathlib import Path
import unittest
from unittest.mock import patch

from app.auth import require_student
from app.models import AssignmentGradingAnswer, ClassroomMember, User
from app.routers import student, student_assignment_image
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


if __name__ == "__main__":
    unittest.main()
