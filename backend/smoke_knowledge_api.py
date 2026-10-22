"""学科 RAG 接口回归：临时数据库与模型替身，不连接线上服务。"""
import unittest
from unittest.mock import patch

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import SubjectKnowledgeChunk, SubjectKnowledgePassage, TeacherSubject, User
from app.routers.teacher import router


class KnowledgeApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([User(id=1, name="数学老师", role="teacher"),
                        User(id=2, name="英语老师", role="teacher"),
                        User(id=3, name="学生", role="student", student_no="test-3")])
            db.flush()
            db.add_all([TeacherSubject(teacher_id=1, subject="math"),
                        TeacherSubject(teacher_id=2, subject="english")])
            db.commit()
        app = FastAPI()
        app.include_router(router)

        def database():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer mock-1"}
        self.disabled = patch("app.services.rag_milvus.configured", return_value=False)
        self.disabled.start()
        self.enterContext(patch("app.services.bailian_rerank.configured", return_value=False))

    def tearDown(self):
        self.disabled.stop()
        self.client.close()
        self.engine.dispose()

    def add(self, **changes):
        payload = {"title": "二次函数", "content": "二次函数图像是抛物线，对称轴由系数决定。", "source_name": "教学讲义"}
        payload.update(changes)
        response = self.client.post("/api/teacher/knowledge/math", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_text_search_and_delete(self):
        saved = self.add()
        self.assertGreater(saved["passage_count"], 0)
        self.assertEqual(saved["vector_status"], "disabled")
        listing = self.client.get("/api/teacher/knowledge/math", headers=self.headers).json()
        self.assertFalse(listing["vector_enabled"])
        self.assertEqual(listing["items"][0]["passage_count"], saved["passage_count"])
        found = self.client.post("/api/teacher/knowledge/math/search", headers=self.headers,
                                 json={"query": "二次函数的对称轴"}).json()
        self.assertEqual(found["items"][0]["document_id"], saved["id"])
        self.assertIn("资料", found["items"][0]["citation"])
        self.assertIsNone(found["items"][0]["page_number"])
        deleted = self.client.delete(f"/api/teacher/knowledge/math/{saved['id']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgePassage).count(), 0)
        self.assertEqual(self.client.post("/api/teacher/knowledge/math/search", headers=self.headers,
                                         json={"query": "二次函数"}).json()["items"], [])

    def test_subject_and_role_permissions(self):
        for path in ("/api/teacher/knowledge/english", "/api/teacher/knowledge/english/search",
                     "/api/teacher/knowledge/english/reindex", "/api/teacher/knowledge/english/import-pdf"):
            response = (self.client.get(path, headers=self.headers) if path.endswith("english")
                        else self.client.post(path, headers=self.headers,
                                              json={"query": "grammar"}) if not path.endswith("import-pdf")
                        else self.client.post(path, headers=self.headers, files={"file": ("test.pdf", b"bad")}))
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get("/api/teacher/knowledge/math").status_code, 401)
        self.assertEqual(self.client.get("/api/teacher/knowledge/math",
                                         headers={"Authorization": "Bearer mock-3"}).status_code, 403)

    def test_invalid_input(self):
        for payload in ({"title": " ", "content": "valid"}, {"title": "valid", "content": " "}):
            response = self.client.post("/api/teacher/knowledge/math", headers=self.headers, json=payload)
            self.assertEqual(response.status_code, 422)
        for payload in ({"query": " "}, {"query": "函数", "limit": 0}, {"query": "函数", "limit": 9}):
            response = self.client.post("/api/teacher/knowledge/math/search", headers=self.headers, json=payload)
            self.assertEqual(response.status_code, 422)

    @staticmethod
    def pdf_bytes():
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((60, 80), "Quadratic functions and parabolas.")
            pdf.new_page()
            pdf.new_page().insert_text((60, 80), "Discriminant determines the number of real roots.")
            return pdf.tobytes()

    def test_pdf_pages_and_reindex(self):
        response = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                    files={"file": ("lesson.pdf", self.pdf_bytes(), "application/pdf")},
                                    data={"title": "Quadratic lesson"})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual((saved["page_count"], saved["indexed_pages"]), (3, 2))
        self.assertTrue(saved["warnings"])
        with self.sessions() as db:
            before = [(row.id, row.page_number) for row in db.query(SubjectKnowledgePassage).order_by(SubjectKnowledgePassage.id)]
        with patch("app.services.rag_milvus.configured", return_value=True), \
                patch("app.services.rag_milvus.upsert_passages") as upsert:
            rebuilt = self.client.post("/api/teacher/knowledge/math/reindex", headers=self.headers)
            self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
            self.assertEqual(rebuilt.json()["vector_status"], "ready")
            self.assertEqual(rebuilt.json()["passage_count"], len(before))
            self.assertTrue(upsert.called)
        with self.sessions() as db:
            after = [(row.id, row.page_number) for row in db.query(SubjectKnowledgePassage).order_by(SubjectKnowledgePassage.id)]
        self.assertEqual(before, after)
        found = self.client.post("/api/teacher/knowledge/math/search", headers=self.headers,
                                 json={"query": "discriminant real roots"}).json()
        self.assertEqual(found["items"][0]["page_number"], 3)

    def test_bad_or_image_only_pdf(self):
        for data in (b"not a pdf", b""):
            response = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                        files={"file": ("bad.pdf", data, "application/pdf")})
            self.assertEqual(response.status_code, 422, response.text)
        with pymupdf.open() as pdf:
            pdf.new_page()
            data = pdf.tobytes()
        response = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                    files={"file": ("scan.pdf", data, "application/pdf")})
        self.assertEqual(response.status_code, 422)
        self.assertIn("OCR", response.json()["detail"])
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgeChunk).count(), 0)

    def test_vector_outage_preserves_document(self):
        with patch("app.services.rag_milvus.configured", return_value=True), \
                patch("app.services.rag_milvus.upsert_passages", side_effect=ConnectionError):
            saved = self.add()
        self.assertEqual(saved["vector_status"], "pending")
        self.assertTrue(saved["warnings"])
        with self.sessions() as db:
            self.assertIsNotNone(db.get(SubjectKnowledgeChunk, saved["id"]))
        with patch("app.services.rag_milvus.configured", return_value=True), \
                patch("app.services.rag_milvus.delete_document", side_effect=ConnectionError):
            deleted = self.client.delete(f"/api/teacher/knowledge/math/{saved['id']}", headers=self.headers)
        self.assertTrue(deleted.json()["warnings"])
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgePassage).count(), 0)

    def test_teacher_knowledge_tool_scope(self):
        from app.agent.teacher_tools import build_teacher_tools

        self.add()
        with self.sessions() as db:
            tool = next(item for item in build_teacher_tools(db, db.get(User, 1)) if item.name == "search_teaching_knowledge")
            self.assertIn("任教范围", tool.invoke({"query": "grammar", "subject": "english"}))
            answer = tool.invoke({"query": "二次函数的对称轴"})
            self.assertIn("资料", answer)
            self.assertIn("教学讲义", answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
