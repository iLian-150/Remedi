"""Application startup and shutdown hooks."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import SessionLocal, init_db
from .services import deferral as deferral_svc
from .services import knowledge_jobs, reviews as review_svc

logger = logging.getLogger(__name__)


async def _deferred_grading_loop() -> None:
    """Grade submissions whose assignment deadline has passed."""
    while True:
        try:
            await asyncio.sleep(60)
            await asyncio.to_thread(_grade_due_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep upstream details out of logs; they can contain private data.
            logger.warning("延迟批改本轮失败（error=%s）", type(exc).__name__)


def _grade_due_once() -> None:
    """Run deadline grading with its own database session."""
    db = SessionLocal()
    try:
        deferral_svc.grade_due(db)
    finally:
        db.close()


def _backfill_review_records() -> None:
    db = SessionLocal()
    try:
        repaired = review_svc.backfill_missing_review_records(db)
        if repaired:
            logger.info("已补齐 %d 条历史待审核记录", repaired)
    except Exception:
        db.rollback()
        logger.exception("补齐历史低正确率作业审核记录失败")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Own process-scoped workers and database initialization."""
    init_db()
    _backfill_review_records()
    try:
        knowledge_jobs.start_worker()
    except Exception as exc:
        # Queued jobs remain in the database and can resume after restart.
        logger.warning("导入任务队列启动失败（error=%s）", type(exc).__name__)

    grading_task = None
    try:
        grading_task = asyncio.create_task(
            _deferred_grading_loop(), name="deferred-grading",
        )
        yield
    finally:
        if grading_task is not None:
            grading_task.cancel()
            try:
                await grading_task
            except asyncio.CancelledError:
                pass
        knowledge_jobs.stop_worker()
