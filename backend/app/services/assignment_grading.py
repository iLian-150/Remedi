"""Persistent background grading for complete student assignments."""
import logging
import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_

from ..config import settings
from ..database import SessionLocal
from ..models import (
    AssignmentGradingAnswer,
    AssignmentGradingCheckpoint,
    AssignmentGradingJob,
    Question,
    QuestionGroup,
    QuestionGroupMember,
    Submission,
    SubmissionImage,
    User,
)
from . import reviews as review_svc, scoring as scoring_svc
from .diagnosis import diagnose_visual_submission
from .providers import get_provider

logger = logging.getLogger(__name__)
_wake = threading.Event()
_stop = threading.Event()
_worker_lock = threading.Lock()
_worker = None


class AnswerRecognitionError(ValueError):
    """模型未识别出作答；只保存安全的题号，不保存模型原文。"""

    def __init__(self, question_index: int):
        self.question_index = question_index
        super().__init__("answer not recognized")


def _diagnose_with_retry(diagnose, question_index: int) -> dict:
    """空结果可能是视觉模型偶发漏识别，重试一次；不凭空生成评分。"""
    for attempt in range(2):
        try:
            diagnosis = diagnose()
        except (RuntimeError, TimeoutError):
            if attempt == 1:
                raise
            logger.info("模型调用暂时失败，正在重试本题（question_index=%s）", question_index)
            continue
        if diagnosis.get("steps"):
            return diagnosis
        if attempt == 0:
            logger.info("作答未识别，正在重试（question_index=%s）", question_index)
    raise AnswerRecognitionError(question_index)


def enqueue(job_id: int) -> None:
    _wake.set()


def start_worker() -> None:
    """Recover interrupted queued work and start the process-scoped worker."""
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        with SessionLocal() as db:
            db.query(AssignmentGradingJob).filter(
                AssignmentGradingJob.status.in_(["processing", "failed"])
            ).update({
                AssignmentGradingJob.status: "queued",
                AssignmentGradingJob.next_attempt_at: None,
                AssignmentGradingJob.updated_at: datetime.now(),
            }, synchronize_session=False)
            db.commit()
        _worker = threading.Thread(
            target=_worker_loop, name="assignment-grading", daemon=True,
        )
        _worker.start()
        _wake.set()


def stop_worker() -> None:
    _stop.set()
    _wake.set()
    worker = _worker
    if worker is not None:
        worker.join(timeout=5)


def _next_ready_job_id():
    with SessionLocal() as db:
        job = db.query(AssignmentGradingJob.id).filter(
            AssignmentGradingJob.status == "queued",
            or_(AssignmentGradingJob.next_attempt_at.is_(None),
                AssignmentGradingJob.next_attempt_at <= datetime.now()),
        ).order_by(AssignmentGradingJob.created_at, AssignmentGradingJob.id).first()
        return job[0] if job else None


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            job_id = _next_ready_job_id()
            if job_id is None:
                _wake.wait(timeout=20)
                _wake.clear()
                continue
            _grade_job(job_id)
        except Exception as exc:
            missing_module = getattr(exc, "name", None) if isinstance(exc, ModuleNotFoundError) else None
            logger.warning(
                "整份作业后台批改任务异常（error=%s, module=%s）",
                type(exc).__name__, missing_module or "unknown",
            )
            time.sleep(1)


def _draft_image_path(relative_path: str) -> Path:
    root = Path(settings.ASSIGNMENT_DRAFT_DIR).resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise ValueError("作答图片路径无效")
    return target


def remove_draft_image(relative_path: str) -> None:
    try:
        _draft_image_path(relative_path).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("清理作答暂存图片失败")


def _copy_to_uploads(source: Path) -> str:
    extension = source.suffix.lower()
    basename = f"{datetime.now():%Y%m%d%H%M%S}_{os.urandom(8).hex()}{extension}"
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    target = Path(settings.UPLOAD_DIR) / basename
    shutil.copyfile(source, target)
    return basename


def _grade_job(job_id: int) -> None:
    db = SessionLocal()
    image_paths_to_remove = []
    final_image_paths = []
    stage = "initializing"
    try:
        job = db.query(AssignmentGradingJob).filter_by(id=job_id).first()
        if job is None or job.status != "queued":
            return
        claimed = db.query(AssignmentGradingJob).filter(
            AssignmentGradingJob.id == job_id,
            AssignmentGradingJob.status == "queued",
            or_(AssignmentGradingJob.next_attempt_at.is_(None),
                AssignmentGradingJob.next_attempt_at <= datetime.now()),
        ).update({AssignmentGradingJob.status: "processing"}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
        db.refresh(job)
        from ..agent.subjects import build_subject_context
        answers = db.query(AssignmentGradingAnswer).filter_by(job_id=job.id).all()
        questions = db.query(Question).filter(
            Question.assignment_id == job.assignment_id
        ).order_by(Question.order_num, Question.id).all()
        question_ids = {question.id for question in questions}
        answer_by_question = {answer.question_id: answer for answer in answers}
        if not questions or question_ids - set(answer_by_question):
            raise ValueError("incomplete assignment answers")

        job.status = "processing"
        job.progress = 0
        job.total_questions = len(questions)
        job.error = None
        job.next_attempt_at = None
        job.updated_at = datetime.now()
        db.commit()

        group_stems = {}
        group_rows = db.query(QuestionGroupMember.question_id, QuestionGroup.stem).join(
            QuestionGroup, QuestionGroup.id == QuestionGroupMember.group_id,
        ).filter(QuestionGroupMember.question_id.in_(question_ids)).all()
        group_stems = {question_id: stem for question_id, stem in group_rows}

        fingerprints = {}
        cached_diagnoses = {}
        for question in questions:
            answer = answer_by_question[question.id]
            source = {
                "subject": question.subject, "stem": question.stem,
                "standard_answer": question.standard_answer, "knowledge_point": question.knowledge_point,
                "group_stem": group_stems.get(question.id), "answer_text": answer.answer_text,
                "image_hash": (hashlib.sha256(_draft_image_path(answer.image_path).read_bytes()).hexdigest()
                               if answer.image_path else None),
                "vision_model": settings.LLM_VISION_MODEL or settings.DASHSCOPE_VISION_MODEL,
                "text_model": settings.LLM_MODEL or settings.DASHSCOPE_MODEL,
            }
            fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            fingerprints[question.id] = fingerprint
            checkpoint = db.get(AssignmentGradingCheckpoint, answer.id)
            if checkpoint and checkpoint.fingerprint == fingerprint:
                diagnosis = json.loads(checkpoint.diagnosis_json)
                if diagnosis.get("steps"):
                    cached_diagnoses[question.id] = diagnosis

        provider = get_provider()
        inferred_points = {}
        for question in questions:
            cached = cached_diagnoses.get(question.id)
            known_point = (question.knowledge_point or "").strip()
            if cached or known_point:
                inferred_points[question.id] = cached["knowledge_point"] if cached else known_point
                continue
            stage = f"knowledge_point:{question.id}"
            source = "\n".join(filter(None, (
                group_stems.get(question.id), question.stem,
            )))
            try:
                inferred = provider.guess_knowledge_point(source, subject=question.subject)
            except Exception as exc:
                logger.warning("作业知识点识别失败，使用题目知识点（error=%s）", type(exc).__name__)
                inferred = ""
            inferred_points[question.id] = (inferred or "").strip()[:64] or question.knowledge_point

        rag_by_subject = {}
        pending_questions = [q for q in questions if q.id not in cached_diagnoses]
        for subject in {question.subject for question in pending_questions}:
            stage = f"retrieval:{subject}"
            subject_questions = [question for question in pending_questions if question.subject == subject]
            query_parts = []
            for question in subject_questions:
                if group_stems.get(question.id):
                    query_parts.append(group_stems[question.id])
                query_parts.extend((
                    inferred_points[question.id], question.stem,
                    question.standard_answer or "",
                ))
            try:
                rag_by_subject[subject] = build_subject_context(
                    db, subject, "\n".join(part for part in query_parts if part)[:12000],
                )
            except Exception as exc:
                logger.warning("作业知识库检索失败（subject=%s, error=%s）", subject, type(exc).__name__)
                rag_by_subject[subject] = ""

        student = db.query(User).filter_by(id=job.student_id).first()
        if student is None:
            raise ValueError("student not found")

        grading_results = []
        for index, question in enumerate(questions, start=1):
            stage = f"diagnosis:{question.id}"
            answer = answer_by_question[question.id]
            knowledge_point = inferred_points[question.id]
            rag_context = rag_by_subject.get(question.subject, "")
            cached = cached_diagnoses.get(question.id)
            if cached:
                visual_steps = cached["steps"]
                confidence = cached.get("confidence", 0.5)
                source_image_path = _draft_image_path(answer.image_path) if answer.image_path else None
            elif answer.image_path:
                source_path = _draft_image_path(answer.image_path)
                image_bytes = source_path.read_bytes()
                content_type = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp",
                }.get(source_path.suffix.lower(), "image/jpeg")
                context = (
                    f"学科：{question.subject}\n知识点：{knowledge_point}\n"
                    f"题目：{question.stem}\n教师参考答案或步骤：{question.standard_answer or '未提供'}\n"
                    f"大题材料：{group_stems.get(question.id, '')}"
                )
                diagnosis = _diagnose_with_retry(
                    lambda: provider.diagnose_homework_image(
                        image_bytes, content_type, context, knowledge_context=rag_context,
                        timeout_seconds=settings.ASSIGNMENT_GRADING_TIMEOUT_SECONDS,
                    ), index,
                )
                visual_steps = diagnosis.get("steps") or []
                source_image_path = source_path
                confidence = diagnosis.get("confidence", 0.5)
            else:
                student_work = [line.strip() for line in (answer.answer_text or "").splitlines()
                                if line.strip()]
                diagnosis = _diagnose_with_retry(
                    lambda: provider.diagnose_homework_text(
                        subject=question.subject,
                        question_text="\n".join(filter(None, (
                            group_stems.get(question.id), question.stem,
                            f"教师参考答案或步骤：{question.standard_answer or '未提供'}",
                        ))),
                        student_work=student_work,
                        knowledge_context=rag_context,
                    ), index,
                )
                visual_steps = diagnosis.get("steps") or []
                source_image_path = None
                confidence = diagnosis.get("confidence", 0.5)
            if not cached:
                db.merge(AssignmentGradingCheckpoint(
                    answer_id=answer.id, fingerprint=fingerprints[question.id],
                    diagnosis_json=json.dumps({"steps": visual_steps, "confidence": confidence,
                                               "knowledge_point": knowledge_point}, ensure_ascii=False),
                ))
            grading_results.append((question, answer, knowledge_point, visual_steps,
                                    confidence, source_image_path))
            job.progress = index
            job.updated_at = datetime.now()
            db.commit()

        # 先完成整份作业的模型判断，再一次性写入提交，避免中途模型失败时只生成部分成绩。
        created_submissions = []
        stage = "persisting_results"
        for question, answer, knowledge_point, visual_steps, confidence, source_image_path in grading_results:
            image_path = None
            if source_image_path is not None:
                image_path = _copy_to_uploads(source_image_path)
                final_image_paths.append(image_path)
            submission, steps, errors = diagnose_visual_submission(
                db, student, question, visual_steps, commit=False,
            )
            for error in errors:
                error.knowledge_point = knowledge_point
            if image_path:
                db.add(SubmissionImage(
                    submission_id=submission.id,
                    file_path=image_path,
                    file_name=(answer.image_name or "作答图片")[:255],
                ))
            answer.submission_id = submission.id
            db.flush()
            created_submissions.append((submission, confidence, visual_steps))

        db.flush()
        for submission, _confidence, _visual_steps in created_submissions:
            scoring_svc.persist_ai_score(db, submission, commit=False)
        # Review aggregation queries scores with autoflush disabled; persist the
        # pending rows inside this transaction before it checks for missing scores.
        db.flush()
        for submission, _confidence, _visual_steps in created_submissions:
            review_svc.create_review_if_needed(db, submission, commit=False)
        job.status = "completed"
        job.next_attempt_at = None
        job.progress = job.total_questions
        job.updated_at = datetime.now()
        db.commit()
        for answer in answers:
            if answer.image_path:
                image_paths_to_remove.append(_draft_image_path(answer.image_path))
    except Exception as exc:
        db.rollback()
        database_error = getattr(exc, "orig", None)
        sqlite_detail = (
            str(database_error)[:200]
            if getattr(database_error, "sqlite_errorname", None)
            else "unavailable"
        )
        root = exc
        seen = set()
        while id(root) not in seen:
            seen.add(id(root))
            cause = root.__cause__ or root.__context__
            if cause is None:
                break
            root = cause
        logger.warning(
            "整份作业后台批改失败（job_id=%s, stage=%s, error=%s, cause=%s, database=%s）",
            job_id, stage, type(exc).__name__, type(root).__name__, sqlite_detail,
        )
        job = db.query(AssignmentGradingJob).filter_by(id=job_id).first()
        if job is not None and job.status == "completed":
            return
        if job is not None:
            job.status = "queued"
            job.retry_count = (job.retry_count or 0) + 1
            delay = min(300, 30 * 2 ** min(job.retry_count - 1, 4))
            job.next_attempt_at = datetime.now() + timedelta(seconds=delay)
            job.error = "批改暂未完成，后台将自动重试。"
            job.updated_at = datetime.now()
            db.commit()
        for relative_path in final_image_paths:
            try:
                (Path(settings.UPLOAD_DIR) / relative_path).unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        db.close()
        for image_path in image_paths_to_remove:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass
