"""持久化图形任务，发布前后均由服务端完成。"""
import logging
import threading

from ..database import SessionLocal
from ..models import DiagramJob, QuestionGroup
from .diagram_generation import generate_figure

logger = logging.getLogger(__name__)
_wake = threading.Event()
_stop = threading.Event()
_worker = None


def enqueue():
    _wake.set()


def start_worker():
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _stop.clear()
    with SessionLocal() as db:
        db.query(DiagramJob).filter_by(status="processing").update({DiagramJob.status: "queued"})
        db.commit()
    _worker = threading.Thread(target=_loop, name="diagram-jobs", daemon=True)
    _worker.start()
    enqueue()


def stop_worker():
    _stop.set()
    _wake.set()
    if _worker is not None:
        _worker.join(timeout=5)


def _loop():
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                job = db.query(DiagramJob).filter_by(status="queued").order_by(DiagramJob.id).first()
                job_id = job.id if job else None
            if job_id is None:
                _wake.wait(timeout=20)
                _wake.clear()
                continue
            _run(job_id)
        except Exception as exc:
            logger.warning("图形任务异常（%s）", type(exc).__name__)
            _stop.wait(1)


def _run(job_id):
    with SessionLocal() as db:
        claimed = db.query(DiagramJob).filter_by(id=job_id, status="queued").update(
            {DiagramJob.status: "processing"}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
        job = db.get(DiagramJob, job_id)
        subject, question_text = job.subject, job.question_text
    try:
        figure, message = generate_figure(subject, question_text)
        figure_json = figure.model_dump_json(exclude_none=True) if figure else None
        status = "completed"
    except Exception:
        figure_json, message, status = None, "图形生成失败，请重试。", "failed"
    with SessionLocal() as db:
        # 先取得写锁，再读取关联，确保与作业发布时关联任务的事务串行。
        updated = db.query(DiagramJob).filter_by(id=job_id, status="processing").update(
            {DiagramJob.status: status, DiagramJob.figure_json: figure_json,
             DiagramJob.message: message}, synchronize_session=False)
        if updated:
            job = db.get(DiagramJob, job_id)
            if job.group_id is not None and status == "completed":
                group = db.get(QuestionGroup, job.group_id)
                if group is not None:
                    group.diagram_json = figure_json
        db.commit()
