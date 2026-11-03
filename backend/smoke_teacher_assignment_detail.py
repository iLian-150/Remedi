"""教师作业详情权限、分组和图形的隔离验证。"""
import unittest

from app.auth import require_teacher
from app.models import ClassroomTeacherSubject, Question, QuestionGroup, QuestionGroupMember, TeacherSubject, User
from app.routers import teacher_assignment_detail
import smoke_diagram_jobs as fixtures


class TeacherAssignmentDetailTests(fixtures.DiagramJobsTest):
    def setUp(self):
        super().setUp()
        self.app.include_router(teacher_assignment_detail.router)

    def test_visible_question_groups_and_permissions(self):
        job = self.job()
        response = self.publish(job)
        self.assertEqual(response.status_code, 200, response.text)
        assignment_id = response.json()["id"]
        with self.sessions() as db:
            db.add(User(id=4, name="shared", role="teacher"))
            db.add(TeacherSubject(teacher_id=4, subject="math"))
            db.add(ClassroomTeacherSubject(classroom_id=1, teacher_id=4, subject="math"))
            hidden_group = QuestionGroup(assignment_id=assignment_id, stem="不可见的物理材料", order_num=2)
            hidden_question = Question(assignment_id=assignment_id, subject="physics", knowledge_point="", stem="不可见的物理题", order_num=2)
            db.add_all([hidden_group, hidden_question])
            db.flush()
            db.add(QuestionGroupMember(question_id=hidden_question.id, group_id=hidden_group.id))
            db.commit()
        url = f"/api/teacher/assignments/{assignment_id}"
        pending = self.client.get(url)
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(pending.json()["groups"][0]["diagram_status"], "queued")
        self.assertIsNone(pending.json()["groups"][0]["diagram"])
        self.run_job(job)
        for teacher_id in (1, 4):
            self.app.dependency_overrides[require_teacher] = lambda teacher_id=teacher_id: User(id=teacher_id, role="teacher", name="teacher")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual([q["prompt"] for q in data["questions"]], ["小题"])
            self.assertEqual([g["stem"] for g in data["groups"]], ["材料"])
            self.assertEqual(data["questions"][0]["group_id"], data["groups"][0]["id"])
            self.assertIsNotNone(data["groups"][0]["diagram"])
            self.assertEqual(data["groups"][0]["diagram_status"], "completed")
        self.app.dependency_overrides[require_teacher] = lambda: User(id=3, role="teacher", name="other")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get("/api/teacher/assignments/999999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
