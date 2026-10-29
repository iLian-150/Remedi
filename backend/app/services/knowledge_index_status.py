"""Keep completed import notifications consistent with explicit index rebuilds."""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import KnowledgeImportJob, SubjectKnowledgeChunk

IMPORT_VECTOR_WARNING = "资料已保存，向量索引暂未就绪，可使用关键词检索，稍后可重建索引。"
SEARCH_VECTOR_WARNING = "向量检索尚未就绪，请检查向量模型和 Milvus 配置；当前使用 BM25，恢复后可重新建立向量索引。"


def refresh_completed_import_indexes(
    db: Session, subject: str, document_ids: list[int], vector_status: str, warnings: list[str],
) -> None:
    """Update index metadata in the caller's transaction; never reopen a task."""
    for offset in range(0, len(document_ids), 200):
        rows = db.query(KnowledgeImportJob).join(
            SubjectKnowledgeChunk, SubjectKnowledgeChunk.id == KnowledgeImportJob.document_id,
        ).filter(
            KnowledgeImportJob.subject == subject,
            SubjectKnowledgeChunk.subject == subject,
            KnowledgeImportJob.status == "completed",
            KnowledgeImportJob.document_id.in_(document_ids[offset:offset + 200]),
        ).all()
        for row in rows:
            previous = json.loads(row.warnings_json or "[]")
            retained = [item for item in previous if item not in {
                IMPORT_VECTOR_WARNING, SEARCH_VECTOR_WARNING,
            }]
            current = list(dict.fromkeys(retained + warnings))
            message = "导入成功" if vector_status == "ready" else "资料已导入，可使用关键词检索"
            if row.vector_status == vector_status and previous == current and row.message == message:
                continue
            row.vector_status = vector_status
            row.message = message
            row.warnings_json = json.dumps(current, ensure_ascii=False)
            row.updated_at = datetime.now()
