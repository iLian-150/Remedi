"""单工作线程执行数据库任务，HTTP 上传完成后即可返回，不依赖浏览器长连接。"""
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..database import SessionLocal
from ..models import KnowledgeImportDismissal, KnowledgeImportJob, SubjectKnowledgeChunk

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"completed", "failed"}
_wake = threading.Event()
_stop = threading.Event()
_worker_lock = threading.Lock()
_worker = None
_VECTOR_WARNING = "资料已保存，向量索引暂未就绪，可使用关键词检索，稍后可重建索引。"


def job_payload(row: KnowledgeImportJob) -> dict:
    return {
        "id": row.id, "subject": row.subject, "filename": row.filename,
        "status": row.status, "stage": row.stage, "progress": row.progress,
        "completed_pages": row.completed_pages, "total_pages": row.total_pages,
        "message": row.message, "document_id": row.document_id,
        "vector_status": row.vector_status, "warnings": json.loads(row.warnings_json or "[]"),
        "error": row.error, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _source_path(relative_path: str) -> Path:
    root = Path(settings.KNOWLEDGE_IMPORT_DIR).resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise ValueError("资料文件路径无效。")
    return target


def _reset_for_retry(db, row) -> None:
    row.status = "queued"
    row.stage = "queued"
    row.message = "等待继续导入"
    row.error = None
    row.updated_at = datetime.now()
    db.query(KnowledgeImportDismissal).filter_by(job_id=row.id).delete(synchronize_session=False)


def enqueue_import(stream, filename: str, subject: str, teacher_id: int) -> dict:
    """分块落盘并校验摘要；唯一索引消除重复点击、断线重发与并发上传。"""
    from .knowledge_import import SUPPORTED_KNOWLEDGE_FORMATS

    filename = (filename or "教学资料").replace("\\", "/").rsplit("/", 1)[-1]
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_KNOWLEDGE_FORMATS:
        raise ValueError("暂不支持此文件格式。支持：" + "、".join(SUPPORTED_KNOWLEDGE_FORMATS) + "。")
    if not re.fullmatch(r"[a-z]{1,32}", subject):
        raise ValueError("学科 Agent 不存在。")
    filename = Path(filename).stem[:255 - len(extension)] + extension
    directory = Path(settings.KNOWLEDGE_IMPORT_DIR) / subject
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (uuid.uuid4().hex + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("xb") as target:
            while block := stream.read(1024 * 1024):
                size += len(block)
                digest.update(block)
                target.write(block)
        if not size:
            raise ValueError("资料文件不能为空。")
        sha256 = digest.hexdigest()
        relative_path = f"{subject}/{sha256}{extension}"
        # 摘要相同的原件不可变。原子创建硬链接让第一个上传获胜，
        # 其他上传复用已完整写好的文件，避免覆盖正在读取的原件。
        try:
            os.link(temporary, _source_path(relative_path))
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)

    created = False
    with SessionLocal() as db:
        row = db.query(KnowledgeImportJob).filter_by(subject=subject, file_sha256=sha256).first()
        if row is None:
            row = KnowledgeImportJob(
                id=uuid.uuid4().hex, subject=subject, filename=filename[:255],
                file_sha256=sha256, file_path=relative_path, created_by=teacher_id,
            )
            db.add(row)
            try:
                db.commit()
                created = True
            except IntegrityError:
                db.rollback()
                row = db.query(KnowledgeImportJob).filter_by(subject=subject, file_sha256=sha256).one()
        duplicate = not created
        # 删除过的文档可以重新导入；历史任务保留，原始文件也继续复用。
        if row.status == "completed" and (
            row.document_id is None or db.get(SubjectKnowledgeChunk, row.document_id) is None
        ):
            row.document_id = None
            row.progress = 0
            row.completed_pages = 0
            row.total_pages = 0
            _reset_for_retry(db, row)
            duplicate = False
        if not duplicate or row.status != "completed":
            db.query(KnowledgeImportDismissal).filter_by(
                job_id=row.id, teacher_id=teacher_id,
            ).delete(synchronize_session=False)
        db.commit()
        result = job_payload(row)
        result["duplicate"] = duplicate
        should_wake = not duplicate or row.status == "queued"
    if should_wake:
        _wake.set()
    return result


def retry_import(db, row: KnowledgeImportJob) -> dict:
    if row.status != "failed":
        raise ValueError("只有失败的导入任务可以重试。")
    if not _source_path(row.file_path).is_file():
        raise ValueError("原始资料文件不存在，请重新上传。")
    # 条件更新确保并发点击只能触发一次重试，不会将正在运行的任务重置。
    updated = db.query(KnowledgeImportJob).filter_by(id=row.id, status="failed").update({
        "status": "queued", "stage": "queued", "message": "等待继续导入",
        "error": None, "updated_at": datetime.now(),
    }, synchronize_session=False)
    if updated:
        db.query(KnowledgeImportDismissal).filter_by(job_id=row.id).delete(synchronize_session=False)
    db.commit()
    db.refresh(row)
    _wake.set()
    return job_payload(row)


class _WorkerStopping(Exception):
    pass


def _report_progress(job_id: str, event: dict) -> None:
    if _stop.is_set():
        raise _WorkerStopping()
    with SessionLocal() as db:
        row = db.get(KnowledgeImportJob, job_id)
        if row is None or row.status != "running":
            return
        stage = event.get("stage", "extracting")
        if stage not in {"extracting", "ocr", "visual", "indexing"}:
            stage = "extracting"
        row.stage = stage
        row.total_pages = max(row.total_pages, int(event.get("total_pages") or 0))
        row.completed_pages = max(row.completed_pages, int(event.get("completed_pages") or 0))
        percentage = 5 + int(85 * min(row.completed_pages, row.total_pages) / row.total_pages) if row.total_pages else 5
        if stage == "indexing":
            percentage = max(percentage, 92)
        row.progress = max(row.progress, min(percentage, 99))
        row.message = str(event.get("message") or {
            "extracting": "正在解析资料", "ocr": "正在识别文字",
            "visual": "正在解析图表", "indexing": "正在建立检索索引",
        }[stage])[:500]
        row.updated_at = datetime.now()
        db.commit()


def _run_job(job_id: str) -> None:
    from .knowledge_import import extract_knowledge_document
    from .subject_rag import prepare_knowledge, sync_knowledge

    try:
        with SessionLocal() as db:
            row = db.get(KnowledgeImportJob, job_id)
            if row is None or row.status != "running":
                return
            document_id = row.document_id
            has_document = document_id is not None and db.get(SubjectKnowledgeChunk, document_id) is not None
            filename, subject, created_by, fingerprint = row.filename, row.subject, row.created_by, row.file_sha256
            path = _source_path(row.file_path)
        if not has_document:
            _report_progress(job_id, {"stage": "extracting"})
            source = path if Path(filename).suffix.lower() == ".pdf" else path.read_bytes()
            extracted = extract_knowledge_document(
                source, filename,
                progress=lambda event: _report_progress(job_id, event),
                checkpoint_dir=path.parent / (path.stem + ".checkpoint"),
                fingerprint=fingerprint,
            )
            pages = extracted["pages"]
            if not pages or not any(str(text).strip() for _, text in pages):
                raise ValueError("文件中没有提取到可检索的文字内容。")
            _report_progress(job_id, {
                "stage": "indexing", "completed_pages": extracted.get("page_count", len(pages)),
                "total_pages": extracted.get("page_count", len(pages)),
                "message": "正在保存资料片段",
            })
            with SessionLocal() as db:
                row = db.get(KnowledgeImportJob, job_id)
                document = SubjectKnowledgeChunk(
                    subject=subject, title=Path(filename).stem[:160] or "教学资料",
                    content="\n\n".join(text for _, text in pages),
                    source_name=filename[:200], created_by=created_by,
                )
                db.add(document)
                result = prepare_knowledge(db, document, pages=pages)
                row.document_id = document.id
                row.vector_status = result.get("vector_status", "pending")
                row.warnings_json = json.dumps(extracted.get("warnings", []), ensure_ascii=False)
                row.progress = max(row.progress, 95)
                row.message = "资料已保存，正在建立向量索引"
                row.updated_at = datetime.now()
                # 文档与关联 ID 必须同一事务提交：进程退出后直接继续向量同步。
                db.commit()
                document_id = document.id
        _report_progress(job_id, {"stage": "indexing", "message": "资料已保存，正在建立向量索引"})
        try:
            with SessionLocal() as db:
                result = sync_knowledge(db, document_id)
        except Exception as exc:
            logger.warning("导入向量同步暂不可用（job=%s, error=%s）", job_id, type(exc).__name__)
            result = {"vector_status": "pending", "warnings": [_VECTOR_WARNING]}
        if _stop.is_set():
            raise _WorkerStopping()
        with SessionLocal() as db:
            row = db.get(KnowledgeImportJob, job_id)
            row.status = "completed"
            row.stage = "completed"
            row.progress = 100
            row.vector_status = result.get("vector_status", "pending")
            row.warnings_json = json.dumps(list(dict.fromkeys(
                json.loads(row.warnings_json or "[]") + result.get("warnings", []),
            )), ensure_ascii=False)
            row.message = "导入成功" if row.vector_status == "ready" else "资料已导入，可使用关键词检索"
            row.error = None
            row.updated_at = datetime.now()
            db.commit()
    except _WorkerStopping:
        # 保持 running，下一次进程启动恢复；旧线程不得把新进程已认领的任务重置。
        return
    except Exception as exc:
        if _stop.is_set():
            return
        # 只记录异常类型；上游响应可能包含凭证或内部信息。
        logger.warning("资料后台导入失败（job=%s, error=%s）", job_id, type(exc).__name__)
        with SessionLocal() as db:
            row = db.get(KnowledgeImportJob, job_id)
            if row is not None:
                row.status = "failed"
                row.message = "导入失败"
                row.error = {
                    FileNotFoundError: "原始资料文件不存在，请重新上传。",
                    ValueError: "文件解析失败，请确认文件完整、内容可读且未加密。",
                    RuntimeError: "文字或图表识别暂不可用，请稍后重试。",
                }.get(type(exc), "资料处理失败，请稍后重试。")
                row.updated_at = datetime.now()
                db.commit()


def _claim_next() -> str | None:
    with SessionLocal() as db:
        row = db.query(KnowledgeImportJob).filter_by(status="queued").order_by(
            KnowledgeImportJob.created_at, KnowledgeImportJob.id,
        ).first()
        if row is None:
            return None
        job_id = row.id
        claimed = db.query(KnowledgeImportJob).filter_by(id=job_id, status="queued").update({
            "status": "running", "stage": "extracting", "message": "正在解析资料",
            "updated_at": datetime.now(),
        }, synchronize_session=False)
        db.commit()
        return job_id if claimed else None


def _worker_loop() -> None:
    while not _stop.is_set():
        job_id = None
        try:
            job_id = _claim_next()
            if job_id:
                _run_job(job_id)
                continue
        except Exception as exc:
            logger.warning("导入任务队列暂不可用（error=%s）", type(exc).__name__)
            if job_id is not None and not _stop.is_set():
                # 写入终态时遇到短暂数据库故障，恢复当前任务而不丢失已提交的文档。
                try:
                    with SessionLocal() as db:
                        db.query(KnowledgeImportJob).filter_by(id=job_id, status="running").update({
                            "status": "queued", "message": "等待继续导入", "updated_at": datetime.now(),
                        }, synchronize_session=False)
                        db.commit()
                except Exception:
                    pass
        _wake.wait(3)
        _wake.clear()


def start_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        with SessionLocal() as db:
            db.query(KnowledgeImportJob).filter_by(status="running").update({
                "status": "queued", "stage": "queued", "message": "等待继续导入",
                "updated_at": datetime.now(),
            }, synchronize_session=False)
            db.commit()
        _stop.clear()
        _worker = threading.Thread(target=_worker_loop, name="knowledge-import", daemon=True)
        _worker.start()


def stop_worker() -> None:
    _stop.set()
    _wake.set()
    if _worker is not None:
        _worker.join(timeout=5)
