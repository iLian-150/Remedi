"""Exercise diagram publication before and after generation using an isolated database."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api_schemas.diagram import FigureSpec
from app.auth import require_student, require_teacher
from app.database import Base, get_db
from app.models import User, Classroom, ClassroomMember, TeacherSubject, ClassroomTeacherSubject
from app.routers import diagrams, student, teacher
from app.services import diagram_jobs

FIGURE = FigureSpec.model_validate({"kind": "coordinate", "bounds": {"x_min": -2, "x_max": 2, "y_min": -2, "y_max": 2}, "elements": [{"type": "point", "x": 0, "y": 0}]})

class DiagramJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.tmp.name) / "test.db"), connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([User(id=1, name="teacher", role="teacher"), User(id=2, name="student", role="student"), User(id=3, name="other", role="teacher"), Classroom(id=1, name="class", created_by=1), TeacherSubject(teacher_id=1, subject="math"), ClassroomTeacherSubject(teacher_id=1, classroom_id=1, subject="math"), ClassroomMember(student_id=2, classroom_id=1)])
            db.commit()
        app = FastAPI()
        app.include_router(diagrams.router)
        app.include_router(teacher.router)
        app.include_router(student.router)
        def get_test_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_teacher] = lambda: User(id=1, role="teacher", name="teacher")
        app.dependency_overrides[require_student] = lambda: User(id=2, role="student", name="student")
        self.app = app
        self.client = TestClient(app)
        self.worker_db = patch.object(diagram_jobs, "SessionLocal", self.sessions)
        self.worker_db.start()

    def tearDown(self):
        self.worker_db.stop()
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def job(self):
        response = self.client.post("/api/teacher/diagrams/jobs", json={"subject": "math", "question_text": "材料\n小题"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def publish(self, job_id, stem="材料"):
        return self.client.post("/api/teacher/assignments", json={"title": "作业", "class_ids": [1], "questions": [{"type": "math", "subject": "math", "prompt": "小题", "group_key": "g1"}], "groups": [{"key": "g1", "stem": stem, "diagram_job_id": job_id}]})

    def detail(self, assignment_id):
        response = self.client.get(f"/api/student/assignments/{assignment_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["groups"][0]

    def run_job(self, job_id, result=(FIGURE, "")):
        with patch.object(diagram_jobs, "generate_figure", return_value=result):
            diagram_jobs._run(job_id)

    def test_publish_before_generation_and_student_refresh(self):
        job = self.job()
        response = self.publish(job)
        self.assertEqual(response.status_code, 200, response.text)
        assignment = response.json()["id"]
        self.assertEqual(self.detail(assignment)["diagram_status"], "queued")
        self.run_job(job)
        group = self.detail(assignment)
        self.assertEqual(group["diagram_status"], "completed")
        self.assertEqual(group["diagram"]["elements"][0]["type"], "point")
        self.assertEqual(self.client.get("/api/teacher/diagrams/jobs").json()[0]["assignment_id"], assignment)

    def test_publish_while_model_is_running(self):
        job = self.job()
        started, finish = threading.Event(), threading.Event()
        def generate(*_args):
            started.set()
            self.assertTrue(finish.wait(10))
            return FIGURE, ""
        with patch.object(diagram_jobs, "generate_figure", side_effect=generate):
            worker = threading.Thread(target=diagram_jobs._run, args=(job,))
            worker.start()
            try:
                self.assertTrue(started.wait(10))
                response = self.publish(job)
                self.assertEqual(response.status_code, 200, response.text)
                assignment = response.json()["id"]
                self.assertEqual(self.detail(assignment)["diagram_status"], "processing")
            finally:
                finish.set()
                worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertIsNotNone(self.detail(assignment)["diagram"])

    def test_completion_before_publication_and_snapshot_validation(self):
        job = self.job()
        self.run_job(job)
        self.assertEqual(self.publish(job, "修改后的材料").status_code, 400)
        response = self.publish(job)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(self.detail(response.json()["id"])["diagram"])
        self.assertEqual(self.publish(job).status_code, 400)

    def test_failure_retry_and_other_teacher_access(self):
        job = self.job()
        response = self.publish(job)
        assignment = response.json()["id"]
        with patch.object(diagram_jobs, "generate_figure", side_effect=RuntimeError("failure")):
            diagram_jobs._run(job)
        self.assertEqual(self.detail(assignment)["diagram_status"], "failed")
        self.app.dependency_overrides[require_teacher] = lambda: User(id=3, role="teacher", name="other")
        self.assertEqual(self.client.get(f"/api/teacher/diagrams/jobs/{job}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/teacher/diagrams/jobs/{job}/retry").status_code, 404)
        self.app.dependency_overrides[require_teacher] = lambda: User(id=1, role="teacher", name="teacher")
        self.assertEqual(self.client.post(f"/api/teacher/diagrams/jobs/{job}/retry").status_code, 200)
        self.run_job(job)
        self.assertEqual(self.detail(assignment)["diagram_status"], "completed")

if __name__ == "__main__":
    unittest.main()
