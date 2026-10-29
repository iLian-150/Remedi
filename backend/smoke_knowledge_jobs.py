"""后台导入任务回归：临时 SQLite 与文件目录，不访问真实模型或业务数据。"""
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import KnowledgeImportJob, SubjectKnowledgeChunk, TeacherSubject, User
from app.routers import teacher
from app.services import knowledge_import, knowledge_jobs as jobs, subject_rag


class KnowledgeJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            "sqlite:///" + str(self.root / "jobs.db"),
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.enterContext(patch.object(jobs, "SessionLocal", self.sessions))
        self.enterContext(patch.object(jobs.settings, "KNOWLEDGE_IMPORT_DIR", str(self.root / "sources"), create=True))
        self.enterContext(patch.object(subject_rag.rag_milvus, "configured", return_value=False))
        self.enterContext(patch.object(knowledge_import, "extract_knowledge_document", side_effect=self.extract))
        jobs._stop.clear()
        self.addCleanup(jobs._stop.clear)
        with self.sessions() as db:
            db.add_all([User(id=1, name="数学老师", role="teacher"), User(id=2, name="英语老师", role="teacher")])
            db.add_all([TeacherSubject(teacher_id=1, subject="math"), TeacherSubject(teacher_id=2, subject="english")])
            db.commit()

    @staticmethod
    def extract(data, filename, *, progress=None, checkpoint_dir=None, fingerprint=None):
        progress({"stage": "extracting", "total_pages": 2, "completed_pages": 0})
        progress({"stage": "ocr", "total_pages": 2, "completed_pages": 1})
        progress({"stage": "ocr", "total_pages": 2, "completed_pages": 2})
        return {"pages": [(1, "一次函数的图像是一条直线。"), (2, "系数决定直线的倾斜方向。")], "page_count": 2, "warnings": []}

    def enqueue(self, data=b"source", subject="math", filename="教材.txt"):
        return jobs.enqueue_import(io.BytesIO(data), filename, subject, 1)

    def get_job(self, job_id):
        with self.sessions() as db:
            return jobs.job_payload(db.get(KnowledgeImportJob, job_id))

    def run_next(self):
        job_id = jobs._claim_next()
        self.assertIsNotNone(job_id)
        jobs._run_job(job_id)
        return self.get_job(job_id)

    def client(self, teacher_id=1):
        app = FastAPI()
        app.include_router(teacher.router)
        def get_test_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = get_test_db
        return TestClient(app, headers={"Authorization": f"Bearer mock-{teacher_id}"})

    def test_upload_returns_202_before_parsing_and_preserves_private_source(self):
        with patch.object(knowledge_import, "extract_knowledge_document") as extract:
            result = self.client().post("/api/teacher/knowledge/math/import", files={"file": ("教材.txt", b"abc")})
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json()["status"], "queued")
        extract.assert_not_called()
        self.assertEqual(list((self.root / "sources" / "math").glob("*.txt"))[0].read_bytes(), b"abc")
        for field in ("file_path", "file_sha256", "created_by"):
            self.assertNotIn(field, result.json())

    def test_duplicate_concurrent_uploads_share_one_job_but_subjects_do_not(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            records = list(pool.map(lambda _: self.enqueue(), range(3)))
        self.assertEqual(len({item["id"] for item in records}), 1)
        self.assertNotEqual(self.enqueue(subject="english")["id"], records[0]["id"])
        self.assertEqual(self.run_next()["status"], "completed")
        self.assertEqual(self.enqueue()["id"], records[0]["id"])

    def test_duplicate_upload_preserves_source_while_worker_is_reading_it(self):
        original = self.enqueue()
        path = next((self.root / "sources" / "math").glob("*.txt"))
        inode = path.stat().st_ino
        with path.open("rb") as reader:
            self.assertEqual(self.enqueue()["id"], original["id"])
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(reader.read(), b"source")
        self.assertFalse(list(path.parent.glob("*.part")))

    def test_vector_failure_completes_and_keeps_committed_document(self):
        initial = self.enqueue()
        def fail_vector(db, document_id):
            # Other Session must already see the document and passage commit.
            with self.sessions() as other:
                self.assertIsNotNone(other.get(SubjectKnowledgeChunk, document_id))
            raise RuntimeError("private upstream response: secret-token")
        with patch.object(subject_rag, "sync_knowledge", side_effect=fail_vector):
            result = self.run_next()
        self.assertEqual(result["id"], initial["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["vector_status"], "pending")
        self.assertEqual(result["progress"], 100)
        self.assertTrue(result["warnings"])
        self.assertNotIn("secret-token", str(result))

    def test_failed_retry_reuses_job_source_and_checkpoint_directory(self):
        initial = self.enqueue()
        calls = []
        def interrupted(data, filename, **kwargs):
            calls.append(kwargs["checkpoint_dir"])
            kwargs["progress"]({"stage": "ocr", "completed_pages": 1, "total_pages": 2})
            if len(calls) == 1:
                raise RuntimeError("upstream key must not leak")
            return self.extract(data, filename, **kwargs)
        with patch.object(knowledge_import, "extract_knowledge_document", side_effect=interrupted):
            failed = self.run_next()
            self.assertEqual(failed["status"], "failed")
            self.assertNotIn("upstream key", str(failed))
            with self.sessions() as db:
                retried = jobs.retry_import(db, db.get(KnowledgeImportJob, initial["id"]))
            self.assertGreaterEqual(retried["progress"], failed["progress"])
            self.assertEqual(self.run_next()["status"], "completed")
        self.assertEqual(calls[0], calls[1])
        with self.sessions() as db:
            self.assertEqual(db.query(KnowledgeImportJob).count(), 1)
            self.assertEqual(db.query(SubjectKnowledgeChunk).count(), 1)

    def test_restart_after_sql_commit_resumes_vector_sync_without_duplicate_parse(self):
        initial = self.enqueue()
        with self.sessions() as db:
            document = SubjectKnowledgeChunk(subject="math", title="已保存", content="先保存再同步")
            db.add(document)
            subject_rag.prepare_knowledge(db, document)
            row = db.get(KnowledgeImportJob, initial["id"])
            row.document_id = document.id
            row.status = "running"
            row.progress = 95
            db.commit()
        fake_thread = Mock()
        fake_thread.is_alive.return_value = False
        with patch.object(jobs, "_worker", None), patch.object(jobs.threading, "Thread", return_value=fake_thread):
            jobs.start_worker()
            self.assertEqual(self.get_job(initial["id"])["status"], "queued")
            with patch.object(knowledge_import, "extract_knowledge_document") as extract:
                result = self.run_next()
            extract.assert_not_called()
        self.assertEqual(result["status"], "completed")
        with self.sessions() as db:
            self.assertEqual(db.query(SubjectKnowledgeChunk).count(), 1)

    def test_progress_never_decreases_during_replay(self):
        row = self.enqueue()
        jobs._claim_next()
        jobs._report_progress(row["id"], {"stage": "ocr", "completed_pages": 8, "total_pages": 10})
        previous = self.get_job(row["id"])
        jobs._report_progress(row["id"], {"stage": "ocr", "completed_pages": 2, "total_pages": 10})
        current = self.get_job(row["id"])
        self.assertEqual(current["completed_pages"], 8)
        self.assertGreaterEqual(current["progress"], previous["progress"])

    def test_permissions_and_explicit_terminal_dismissal(self):
        math = self.enqueue()
        english = self.enqueue(subject="english")
        client = self.client()
        self.assertEqual([item["id"] for item in client.get("/api/teacher/knowledge/import-jobs").json()["items"]], [math["id"]])
        self.assertEqual(client.get(f"/api/teacher/knowledge/import-jobs/{english['id']}").status_code, 403)
        self.assertEqual(client.post(f"/api/teacher/knowledge/import-jobs/{math['id']}/dismiss").status_code, 409)
        jobs._claim_next()
        jobs._run_job(math["id"])
        self.assertEqual(client.post(f"/api/teacher/knowledge/import-jobs/{math['id']}/dismiss").status_code, 200)
        self.assertEqual(client.get("/api/teacher/knowledge/import-jobs").json()["items"], [])
        self.assertEqual(client.post(f"/api/teacher/knowledge/import-jobs/{math['id']}/retry").status_code, 409)
        self.assertEqual(client.post("/api/teacher/knowledge/english/import", files={"file": ("x.txt", b"x")}).status_code, 403)

    def test_empty_and_unsupported_are_rejected_without_jobs(self):
        client = self.client()
        for filename, body in (("x.exe", b"abc"), ("x.txt", b"")):
            with self.subTest(filename=filename):
                result = client.post("/api/teacher/knowledge/math/import", files={"file": (filename, body)})
                self.assertEqual(result.status_code, 422)
        with self.sessions() as db:
            self.assertEqual(db.query(KnowledgeImportJob).count(), 0)

    def test_shutdown_does_not_reset_running_job_or_mark_it_failed(self):
        initial = self.enqueue()
        jobs._claim_next()
        jobs._stop.set()
        jobs._run_job(initial["id"])
        self.assertEqual(self.get_job(initial["id"])["status"], "running")


if __name__ == "__main__":
    unittest.main()
