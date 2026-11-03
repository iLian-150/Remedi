"""已发布作业编辑、权限、作答保护和图形更新。"""
import unittest
import threading
from unittest.mock import patch
from app.auth import require_teacher
from app.models import AssignmentClass, AssignmentExt, AssignmentSetting, Classroom, ClassroomTeacherSubject, DiagramJob, Question
from app.routers import teacher_assignment_edit
import smoke_diagram_jobs as fixtures


class AssignmentEditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DiagramJobsTest(methodName="runTest")
        self.fixture.setUp()
        self.app, self.client, self.sessions = self.fixture.app, self.fixture.client, self.fixture.sessions
        self.app.include_router(teacher_assignment_edit.router)
        self.job = self.fixture.job()
        result = self.fixture.publish(self.job)
        self.assertEqual(result.status_code, 200, result.text)
        self.assignment_id = result.json()["id"]
        self.question_id = result.json()["questions"][0]["id"]
        self.url = f"/api/teacher/assignments/{self.assignment_id}"

    def tearDown(self):
        self.fixture.tearDown()

    def edit(self):
        response = self.client.get(self.url + "/edit")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, data):
        return self.client.put(self.url, json=data)

    def test_edit_preserves_ids_updates_student_and_regenerates_stale_figure(self):
        data = self.edit()
        self.assertFalse(data["content_locked"])
        data["title"] = "修改后的作业"
        data["groups"][0]["stem"] = "修改后的材料"
        data["questions"][0]["prompt"] = "修改后的小题"
        data["questions"][0]["standard_answer"] = "参考解答"
        data["total_score"] = 120
        with patch.object(teacher_assignment_edit.diagram_jobs, "enqueue") as enqueue:
            result = self.save(data)
        self.assertEqual(result.status_code, 200, result.text)
        enqueue.assert_called_once()
        with self.sessions() as db:
            q = db.get(Question, self.question_id)
            self.assertEqual((q.stem, q.standard_answer), ("修改后的小题", "参考解答"))
            old_job = db.get(DiagramJob, self.job)
            self.assertEqual(old_job.status, "cancelled")
            self.assertIsNone(old_job.group_id)
            new_job = db.query(DiagramJob).filter_by(group_id=data["groups"][0]["id"]).one()
            self.assertEqual(new_job.question_text, "修改后的材料\n修改后的小题")
            self.assertEqual(new_job.status, "queued")
        student = self.client.get(f"/api/student/assignments/{self.assignment_id}")
        self.assertEqual(student.status_code, 200, student.text)
        self.assertEqual(student.json()["questions"][0]["id"], self.question_id)
        self.assertEqual(student.json()["questions"][0]["stem"], "修改后的小题")
        self.assertEqual(student.json()["groups"][0]["stem"], "修改后的材料")
        self.assertEqual(self.save(data).status_code, 409)

    def test_old_running_diagram_cannot_overwrite_updated_material(self):
        started, finish = threading.Event(), threading.Event()
        def generate(*_args):
            started.set()
            self.assertTrue(finish.wait(10))
            return fixtures.FIGURE, ""
        with patch.object(fixtures.diagram_jobs, "generate_figure", side_effect=generate):
            worker = threading.Thread(target=fixtures.diagram_jobs._run, args=(self.job,))
            worker.start()
            try:
                self.assertTrue(started.wait(10))
                data = self.edit()
                data["groups"][0]["stem"] = "新材料"
                with patch.object(teacher_assignment_edit.diagram_jobs, "enqueue"):
                    response = self.save(data)
                self.assertEqual(response.status_code, 200, response.text)
            finally:
                finish.set()
                worker.join(10)
            self.assertFalse(worker.is_alive())
        detail = self.client.get(f"/api/student/assignments/{self.assignment_id}").json()
        self.assertIsNone(detail["groups"][0]["diagram"])
        self.assertEqual(detail["groups"][0]["diagram_status"], "queued")
        with self.sessions() as db:
            old = db.get(DiagramJob, self.job)
            self.assertEqual(old.status, "cancelled")
            self.assertIsNone(old.group_id)
            new_id = db.query(DiagramJob).filter_by(group_id=data["groups"][0]["id"]).one().id
        self.fixture.run_job(new_id)
        self.assertIsNotNone(self.client.get(f"/api/student/assignments/{self.assignment_id}").json()["groups"][0]["diagram"])

    def test_settings_and_class_scope_can_be_edited_before_work_starts(self):
        with self.sessions() as db:
            db.add(Classroom(id=2, name="另一个班", created_by=1))
            db.add(ClassroomTeacherSubject(classroom_id=2, teacher_id=1, subject="math"))
            db.commit()
        data = self.edit()
        self.assertEqual({item["id"] for item in data["class_options"]}, {1, 2})
        data["class_ids"] = [1, 999]
        self.assertEqual(self.save(data).status_code, 400)
        data["class_ids"] = [1, 2]
        data["deadline"] = "2099-01-02T18:30:00"
        data["allow_revision"] = True
        response = self.save(data)
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertEqual({row.classroom_id for row in db.query(AssignmentClass).filter_by(assignment_id=self.assignment_id)}, {1, 2})
            self.assertEqual(db.get(AssignmentExt, self.assignment_id).deadline.isoformat(), "2099-01-02T18:30:00")
            self.assertTrue(db.get(AssignmentSetting, self.assignment_id).allow_revision)

    def test_existing_and_newly_saved_answers_protect_question_content(self):
        data = self.edit()
        answer_url = f"/api/student/assignments/{self.assignment_id}/answers/{self.question_id}"
        response = self.client.put(answer_url, data={"answer_text": "x=1"})
        self.assertEqual(response.status_code, 200, response.text)
        data["questions"][0]["prompt"] = "不应覆盖作答的题目"
        response = self.save(data)
        self.assertEqual(response.status_code, 409, response.text)
        current = self.edit()
        self.assertTrue(current["content_locked"])
        current["title"] = "新标题"
        current["description"] = "补充说明"
        response = self.save(current)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/student/assignments/{self.assignment_id}").json()["questions"][0]["stem"], "小题")
        self.assertEqual(self.client.get(f"/api/student/assignments/{self.assignment_id}/grading-status").json()["answered_question_ids"], [self.question_id])

    def test_only_owner_and_complete_question_set_can_edit(self):
        data = self.edit()
        data["questions"][0]["id"] = 999999
        self.assertEqual(self.save(data).status_code, 400)
        # 其他任课教师可以查看作业，但不能编辑原发布者的作业。
        with self.sessions() as db:
            db.add(fixtures.TeacherSubject(teacher_id=3, subject="math"))
            db.add(ClassroomTeacherSubject(classroom_id=1, teacher_id=3, subject="math"))
            db.commit()
        self.app.dependency_overrides[require_teacher] = lambda: fixtures.User(id=3, role="teacher", name="other")
        self.assertEqual(self.client.get(self.url + "/edit").status_code, 404)
        self.assertEqual(self.save(data).status_code, 404)


if __name__ == "__main__":
    unittest.main()
