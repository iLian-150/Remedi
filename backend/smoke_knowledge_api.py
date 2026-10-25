"""学科 RAG 接口回归：临时数据库与模型替身，不连接线上服务。"""
import faulthandler
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import KnowledgeImportJob, SubjectKnowledgeChunk, SubjectKnowledgePassage, TeacherSubject, User
from app.routers.teacher import router
from app.services import knowledge_jobs


class KnowledgeApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="remedi-knowledge-api-")
        self.addCleanup(temporary.cleanup)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False, expire_on_commit=False)
        self.enterContext(patch.object(knowledge_jobs, "SessionLocal", self.sessions))
        self.enterContext(patch.object(knowledge_jobs.settings, "KNOWLEDGE_IMPORT_DIR", temporary.name))
        self.enterContext(patch.object(knowledge_jobs.settings, "RAG_VISUAL_ENABLED", False))
        knowledge_jobs._stop.clear()
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

    def run_import(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        initial = response.json()
        self.assertEqual(initial["status"], "queued")
        self.assertEqual(knowledge_jobs._claim_next(), initial["id"])
        knowledge_jobs._run_job(initial["id"])
        result = self.client.get(f"/api/teacher/knowledge/import-jobs/{initial['id']}", headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_pdf_pages_and_reindex(self):
        response = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                    files={"file": ("lesson.pdf", self.pdf_bytes(), "application/pdf")},
                                    data={"title": "Quadratic lesson"})
        saved = self.run_import(response)
        self.assertEqual(saved["status"], "completed", saved)
        self.assertEqual((saved["completed_pages"], saved["total_pages"]), (3, 3))
        self.assertEqual(saved["progress"], 100)
        self.assertTrue(saved["warnings"])
        with self.sessions() as db:
            before = [(row.id, row.page_number) for row in db.query(SubjectKnowledgePassage).order_by(SubjectKnowledgePassage.id)]
            self.assertEqual({page for _, page in before}, {1, 3})
            self.assertEqual(db.get(SubjectKnowledgeChunk, saved["document_id"]).source_name, "lesson.pdf")
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
        empty = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                 files={"file": ("empty.pdf", b"", "application/pdf")})
        self.assertEqual(empty.status_code, 422, empty.text)
        malformed = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                     files={"file": ("bad.pdf", b"not a pdf", "application/pdf")})
        self.assertEqual(self.run_import(malformed)["status"], "failed")
        with pymupdf.open() as pdf:
            pdf.new_page()
            data = pdf.tobytes()
        response = self.client.post("/api/teacher/knowledge/math/import-pdf", headers=self.headers,
                                    files={"file": ("scan.pdf", data, "application/pdf")})
        blank = self.run_import(response)
        self.assertEqual(blank["status"], "failed")
        self.assertTrue(blank["error"])
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgeChunk).count(), 0)
            self.assertEqual(db.query(KnowledgeImportJob).count(), 2)

    def test_vector_outage_preserves_document(self):
        with patch("app.services.rag_milvus.configured", return_value=True), \
                patch("app.services.rag_milvus.upsert_passages", side_effect=ConnectionError):
            saved = self.add()
        self.assertEqual(saved["vector_status"], "pending")
        self.assertTrue(saved["warnings"])
        with self.sessions() as db:
            self.assertIsNotNone(db.get(SubjectKnowledgeChunk, saved["id"]))
        with patch("app.services.rag_milvus.configured", return_value=True), \
                patch("app.services.rag_milvus.delete_passages", side_effect=ConnectionError):
            deleted = self.client.delete(f"/api/teacher/knowledge/math/{saved['id']}", headers=self.headers)
        self.assertTrue(deleted.json()["warnings"])
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgePassage).count(), 0)

    def test_delayed_delete_cannot_remove_new_subject_vectors_with_reused_document_id(self):
        from app.services import rag_milvus, subject_rag

        saved = self.add()
        with self.sessions() as db:
            old_passage_ids = [row[0] for row in db.query(SubjectKnowledgePassage.id).filter_by(document_id=saved["id"])]
        vectors = {passage_id: saved["id"] for passage_id in old_passage_ids}
        created = {}
        client = Mock()
        client.has_collection.return_value = True

        def upsert(_subject, records):
            for record in records:
                vectors[record["id"]] = record["document_id"]

        def finish_delayed_delete(**request):
            self.assertNotIn("filter", request)
            self.assertEqual(request["ids"], old_passage_ids)
            # The route has committed its SQL deletion. A concurrent English
            # upload now reuses the document ID and finishes its vector sync.
            with self.sessions() as db:
                new = SubjectKnowledgeChunk(subject="english", title="新资料", content="New English source.")
                db.add(new)
                subject_rag.prepare_knowledge(db, new)
                db.commit()
                created["id"] = new.id
                created["status"] = subject_rag.sync_knowledge(db, new.id)["vector_status"]
                created["passage_ids"] = [row[0] for row in db.query(SubjectKnowledgePassage.id).filter_by(document_id=new.id)]
            for passage_id in request["ids"]:
                vectors.pop(passage_id, None)

        client.delete.side_effect = finish_delayed_delete
        with patch.object(rag_milvus, "configured", return_value=True), patch.object(
            rag_milvus, "_client_state", return_value=(rag_milvus._ClientState(client, 2), "test"),
        ), patch.object(rag_milvus, "upsert_passages", side_effect=upsert), patch.object(
            rag_milvus, "delete_document",
        ) as legacy:
            response = self.client.delete(f"/api/teacher/knowledge/math/{saved['id']}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["warnings"], [])
        self.assertEqual(created["id"], saved["id"])
        self.assertEqual(created["status"], "ready")
        self.assertTrue(set(created["passage_ids"]).isdisjoint(old_passage_ids))
        self.assertEqual(set(vectors), set(created["passage_ids"]))
        legacy.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(SubjectKnowledgeChunk, created["id"]).subject, "english")

    def test_teacher_knowledge_tool_scope(self):
        from app.agent.teacher_tools import build_teacher_tools

        self.add()
        with self.sessions() as db:
            tool = next(item for item in build_teacher_tools(db, db.get(User, 1)) if item.name == "search_teaching_knowledge")
            self.assertIn("任教范围", tool.invoke({"query": "grammar", "subject": "english"}))
            ambiguous = tool.invoke({"query": "比较数学和物理的知识点差异"})
            self.assertIn("请先确认要检索哪一门", ambiguous)
            answer = tool.invoke({"query": "二次函数的对称轴"})
            self.assertIn("资料", answer)
            self.assertIn("教学讲义", answer)
            self.assertIn("教师端", answer)
            self.assertIn("教师知识库检索结果", answer)
            self.assertNotIn("当前路由到数学 Agent", answer)
            conflicting_subject = tool.invoke({
                "query": "数学中的二次函数，对称轴如何判断？",
                "subject": "english",
            })
            self.assertIn("教师端数学", conflicting_subject)
            ambiguous_with_subject = tool.invoke({
                "query": "比较数学和英语教材中的函数定义",
                "subject": "math",
            })
            self.assertIn("请先确认要检索哪一门", ambiguous_with_subject)
            no_hits = tool.invoke({"query": "量子引力弦动力矩", "subject": "math"})
            self.assertIn("教师知识库没有检索到", no_hits)

    def test_teacher_knowledge_tool_expands_short_followup_from_same_subject_history(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from app.agent.teacher_tools import build_teacher_tools

        self.add()
        history = [
            HumanMessage(content="二次函数的对称轴是什么？"),
            AIMessage(content="可以用一次项系数和二次项系数判断。"),
        ]
        with self.sessions() as db:
            tool = next(
                item for item in build_teacher_tools(
                    db, db.get(User, 1), history=history,
                )
                if item.name == "search_teaching_knowledge"
            )
            answer = tool.invoke({"query": "为什么呢？", "subject": "math"})

        self.assertIn("教学讲义", answer)
        self.assertIn("教师知识库检索结果", answer)

    def test_multisubject_teacher_followup_infers_subject_from_previous_question(self):
        from langchain_core.messages import HumanMessage
        from app.agent.teacher_tools import build_teacher_tools

        self.add()
        history = [HumanMessage(content="数学中的二次函数对称轴是什么？")]
        with self.sessions() as db:
            db.add(TeacherSubject(teacher_id=1, subject="english"))
            db.commit()
            tool = next(
                item for item in build_teacher_tools(
                    db, db.get(User, 1), history=history,
                )
                if item.name == "search_teaching_knowledge"
            )
            answer = tool.invoke({"query": "为什么呢？"})

        self.assertIn("教师端数学", answer)
        self.assertIn("教学讲义", answer)

    def test_teacher_followup_cannot_override_teaching_subject_scope(self):
        from langchain_core.messages import HumanMessage
        from app.agent.teacher_tools import build_teacher_tools

        self.add()
        history = [HumanMessage(content="英语中的现在完成时怎么用？")]
        with self.sessions() as db:
            tool = next(
                item for item in build_teacher_tools(
                    db, db.get(User, 1), history=history,
                )
                if item.name == "search_teaching_knowledge"
            )
            answer = tool.invoke({"query": "为什么呢？"})

        self.assertIn("不在你当前的任教范围", answer)
        self.assertNotIn("教师知识库检索结果", answer)

    def test_teacher_tool_cannot_hide_ambiguous_original_subject_with_model_argument(self):
        from app.agent.teacher_tools import build_teacher_tools

        with self.sessions() as db:
            db.add(TeacherSubject(teacher_id=1, subject="english"))
            db.commit()
            tool = next(
                item for item in build_teacher_tools(
                    db, db.get(User, 1),
                    current_user_text="比较数学和英语教材里的函数概念。",
                )
                if item.name == "search_teaching_knowledge"
            )
            answer = tool.invoke({
                "query": "数学二次函数的对称轴",
                "subject": "math",
            })

        self.assertIn("请先确认要检索哪一门", answer)


class KnowledgeDeleteConcurrencyTests(unittest.TestCase):
    """Real file SQLite connections exercise the route's local lock boundary."""

    def setUp(self):
        faulthandler.dump_traceback_later(20, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        temporary = tempfile.TemporaryDirectory(prefix="remedi-delete-")
        self.addCleanup(temporary.cleanup)
        database_path = Path(temporary.name) / "knowledge.sqlite"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 0.2},
        )
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([User(id=1, name="数学老师", role="teacher"),
                        User(id=2, name="英语老师", role="teacher")])
            db.flush()
            db.add_all([TeacherSubject(teacher_id=1, subject="math"),
                        TeacherSubject(teacher_id=2, subject="english")])
            db.commit()
        self.before_request = None
        self.finished_transactions = []
        app = FastAPI()
        app.include_router(router)

        def database():
            with self.sessions() as db:
                try:
                    if self.before_request:
                        self.before_request(db)
                    yield db
                finally:
                    self.finished_transactions.append(db.in_transaction())

        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer mock-1"}
        self.enterContext(patch("app.services.rag_milvus.configured", return_value=False))
        self.enterContext(patch("app.services.bailian_rerank.configured", return_value=False))

    def save_document(self, subject="math"):
        from app.services.subject_rag import prepare_knowledge

        with self.sessions() as db:
            document = SubjectKnowledgeChunk(subject=subject, title="并发资料", content="二次函数并发删除回归。")
            db.add(document)
            prepare_knowledge(db, document)
            db.commit()
            return document.id, [row[0] for row in db.query(SubjectKnowledgePassage.id).filter_by(document_id=document.id)]

    def assert_document(self, document_id, subject, passage_ids):
        with self.sessions() as db:
            self.assertEqual(db.get(SubjectKnowledgeChunk, document_id).subject, subject)
            self.assertEqual(
                [row[0] for row in db.query(SubjectKnowledgePassage.id).filter_by(document_id=document_id)],
                passage_ids,
            )

    def check_replacement_waits_for_authorized_delete(self, replacement_subject):
        from app.services import subject_rag

        document_id, old_passage_ids = self.save_document()
        authorized_read = threading.Event()
        continue_delete = threading.Event()
        original_delete = subject_rag.delete_knowledge_index

        def pause_after_authorized_read(db, selected_document_id):
            self.assertEqual(selected_document_id, document_id)
            self.assertTrue(db.connection().connection.driver_connection.in_transaction)
            authorized_read.set()
            if not continue_delete.wait(3):
                raise TimeoutError("delete test did not release the local transaction")
            return original_delete(db, selected_document_id)

        with patch.object(subject_rag, "delete_knowledge_index", side_effect=pause_after_authorized_read), \
                patch.object(subject_rag, "delete_vector_index", return_value=[]) as cleanup, \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.client.delete, f"/api/teacher/knowledge/math/{document_id}", headers=self.headers,
            )
            try:
                self.assertTrue(authorized_read.wait(3), "route never reached its authorized document snapshot")
                # A second connection attempts the exact replacement that used
                # to erase a new document through the first request's stale ID.
                with self.sessions() as competing:
                    old = competing.get(SubjectKnowledgeChunk, document_id)
                    self.assertIsNotNone(old)
                    with self.assertRaises(OperationalError) as failure:
                        original_delete(competing, document_id)
                        competing.delete(old)
                        competing.commit()
                    self.assertEqual(failure.exception.orig.sqlite_errorcode & 0xFF, 5)
                    competing.rollback()
            finally:
                continue_delete.set()
            response = pending.result(timeout=5)
        self.assertEqual(response.status_code, 200, response.text)
        cleanup.assert_called_once_with("math", old_passage_ids)
        new_id, new_passage_ids = self.save_document(replacement_subject)
        self.assertEqual(new_id, document_id, "regression requires a reused document ID")
        self.assertTrue(set(old_passage_ids).isdisjoint(new_passage_ids))
        self.assert_document(new_id, replacement_subject, new_passage_ids)

    def test_same_subject_replacement_cannot_enter_authorized_delete_window(self):
        self.check_replacement_waits_for_authorized_delete("math")

    def test_other_subject_replacement_cannot_enter_authorized_delete_window(self):
        self.check_replacement_waits_for_authorized_delete("english")

    def test_existing_real_read_transaction_does_not_begin_twice(self):
        document_id, _ = self.save_document()

        def begin_read(db):
            db.connection().exec_driver_sql("BEGIN")
            db.query(SubjectKnowledgeChunk.id).first()
            self.assertTrue(db.connection().connection.driver_connection.in_transaction)

        self.before_request = begin_read
        response = self.client.delete(f"/api/teacher/knowledge/math/{document_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.finished_transactions[-1])

    def test_changed_existing_read_snapshot_returns_conflict_and_preserves_replacement(self):
        from app.services import subject_rag

        document_id, old_ids = self.save_document()
        snapshot_read = threading.Event()
        resume_request = threading.Event()

        def begin_old_snapshot(db):
            db.connection().exec_driver_sql("BEGIN")
            db.query(SubjectKnowledgeChunk.id).filter_by(id=document_id).first()
            snapshot_read.set()
            if not resume_request.wait(3):
                raise TimeoutError("delete test did not release its old read snapshot")

        self.before_request = begin_old_snapshot
        with patch.object(subject_rag, "delete_vector_index", return_value=[]) as cleanup, \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.client.delete, f"/api/teacher/knowledge/math/{document_id}", headers=self.headers,
            )
            try:
                self.assertTrue(snapshot_read.wait(3), "request did not establish the old read snapshot")
                with self.sessions() as competing:
                    old = competing.get(SubjectKnowledgeChunk, document_id)
                    subject_rag.delete_knowledge_index(competing, document_id)
                    competing.delete(old)
                    competing.commit()
                new_id, new_ids = self.save_document("english")
            finally:
                resume_request.set()
            response = pending.result(timeout=5)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(self.finished_transactions[-1])
        cleanup.assert_not_called()
        self.assertEqual(new_id, document_id)
        self.assertTrue(set(old_ids).isdisjoint(new_ids))
        self.assert_document(new_id, "english", new_ids)

    def test_rejected_delete_rolls_back_before_request_session_closes(self):
        from app.services import subject_rag

        document_id, passage_ids = self.save_document("english")
        for subject, selected_id, expected in (("english", document_id, 403), ("math", document_id, 404)):
            with self.subTest(subject=subject):
                with patch.object(subject_rag, "delete_vector_index") as cleanup:
                    response = self.client.delete(
                        f"/api/teacher/knowledge/{subject}/{selected_id}", headers=self.headers,
                    )
                self.assertEqual(response.status_code, expected, response.text)
                self.assertFalse(self.finished_transactions[-1])
                cleanup.assert_not_called()
                self.save_document()
        self.assert_document(document_id, "english", passage_ids)

    def test_remote_cleanup_runs_after_commit_and_allows_independent_writer(self):
        from app.services import subject_rag

        document_id, old_ids = self.save_document()
        cleanup_started = threading.Event()
        finish_cleanup = threading.Event()

        def delayed_cleanup(subject, passage_ids):
            self.assertEqual(subject, "math")
            self.assertEqual(passage_ids, old_ids)
            cleanup_started.set()
            if not finish_cleanup.wait(3):
                raise TimeoutError("delete test did not finish its remote cleanup")
            return []

        with patch.object(subject_rag, "delete_vector_index", side_effect=delayed_cleanup), \
                ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.client.delete, f"/api/teacher/knowledge/math/{document_id}", headers=self.headers,
            )
            try:
                self.assertTrue(cleanup_started.wait(3), "route never reached remote cleanup")
                with self.sessions() as independent:
                    self.assertIsNone(independent.get(SubjectKnowledgeChunk, document_id))
                    self.assertEqual(independent.query(SubjectKnowledgePassage).count(), 0)
                # This independently committed write must succeed while remote
                # cleanup is paused, rather than waiting on the delete lock.
                new_id, new_ids = self.save_document("english")
            finally:
                finish_cleanup.set()
            response = pending.result(timeout=5)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(new_id, document_id)
        self.assertTrue(set(old_ids).isdisjoint(new_ids))
        self.assert_document(new_id, "english", new_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
