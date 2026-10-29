"""Index rebuilds update completed notifications without changing task ownership."""
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import KnowledgeImportDismissal, KnowledgeImportJob, SubjectKnowledgeChunk, User
from app.services import subject_rag
from app.services.knowledge_index_status import IMPORT_VECTOR_WARNING, SEARCH_VECTOR_WARNING


class ImportIndexStatusTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.enterContext(patch.object(subject_rag.rag_milvus, "configured", return_value=False))
        self.db.add(User(id=1, name="fixture", role="teacher"))
        self.math = SubjectKnowledgeChunk(subject="math", title="fixture", content="一次函数的斜率。")
        self.english = SubjectKnowledgeChunk(subject="english", title="fixture", content="grammar")
        self.db.add_all([self.math, self.english])
        self.db.commit()
        self.job = self.add_job("completed", self.math)
        self.db.add(KnowledgeImportDismissal(job_id=self.job.id, teacher_id=1))
        self.db.commit()

    def add_job(self, status, document):
        name = f"job-{self.db.query(KnowledgeImportJob).count()}"
        row = KnowledgeImportJob(
            id=name, subject=document.subject, filename="fixture.txt", file_sha256=name,
            file_path="fixture.txt", created_by=1, status=status, stage=status,
            progress=100, document_id=document.id, vector_status="disabled",
            message="资料已导入，可使用关键词检索",
            warnings_json=json.dumps(["OCR confidence warning", IMPORT_VECTOR_WARNING, SEARCH_VECTOR_WARNING]),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def reindex(self, status, warnings=()):
        with patch.object(subject_rag, "_sync_vectors", return_value=(status, list(warnings))):
            return subject_rag.reindex_subject(self.db, "math")

    def test_ready_status_removes_only_vector_warnings_and_preserves_dismissal(self):
        result = self.reindex("ready")
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(result["vector_status"], "ready")
        self.assertEqual(self.job.vector_status, "ready")
        self.assertEqual(self.job.message, "导入成功")
        self.assertEqual(json.loads(self.job.warnings_json), ["OCR confidence warning"])
        self.assertEqual((self.job.status, self.job.stage, self.job.progress), ("completed", "completed", 100))
        self.assertEqual(self.db.query(KnowledgeImportDismissal).count(), 1)

    def test_failed_rebuild_retains_document_and_deduplicates_warning(self):
        self.reindex("pending", [SEARCH_VECTOR_WARNING, SEARCH_VECTOR_WARNING])
        self.db.commit()
        self.assertEqual(self.job.vector_status, "pending")
        self.assertEqual(json.loads(self.job.warnings_json), ["OCR confidence warning", SEARCH_VECTOR_WARNING])
        self.assertEqual(self.job.status, "completed")
        self.assertIsNotNone(self.db.get(SubjectKnowledgeChunk, self.math.id))

    def test_other_subjects_running_and_failed_tasks_remain_untouched(self):
        others = [self.add_job(status, doc) for status, doc in [
            ("completed", self.english), ("running", self.math), ("failed", self.math),
        ]]
        snapshot = [(x.vector_status, x.message, x.warnings_json, x.status) for x in others]
        self.reindex("ready")
        self.db.commit()
        self.assertEqual([(x.vector_status, x.message, x.warnings_json, x.status) for x in others], snapshot)

    def test_disabled_index_removes_vector_warning_but_preserves_ocr_warning(self):
        subject_rag.reindex_subject(self.db, "math")
        self.db.commit()
        self.assertEqual(self.job.vector_status, "disabled")
        self.assertEqual(json.loads(self.job.warnings_json), ["OCR confidence warning"])

    def test_caller_can_rollback_status_update_after_remote_index_work(self):
        self.reindex("ready")
        self.db.rollback()
        self.assertEqual(self.job.vector_status, "disabled")
        self.assertIn(IMPORT_VECTOR_WARNING, json.loads(self.job.warnings_json))

    def test_repeated_success_does_not_change_notification_timestamp(self):
        self.reindex("ready")
        self.db.commit()
        timestamp = self.job.updated_at
        self.reindex("ready")
        self.db.commit()
        self.assertEqual(self.job.updated_at, timestamp)


if __name__ == "__main__":
    unittest.main()
