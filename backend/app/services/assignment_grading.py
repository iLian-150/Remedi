"""Persistent background grading for complete student assignments."""
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import SessionLocal
from ..models import (
    AssignmentGradingAnswer,
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
                AssignmentGradingJob.status == "processing"
            ).update({
                AssignmentGradingJob.status: "queued",
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
            AssignmentGradingJob.status == "queued"
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
            logger.warning("整份作业后台批改任务异常（error=%s）", type(exc).__name__)
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
    from .agent.subjects import build_subject_context

    db = SessionLocal()
    image_paths_to_remove = []
    final_image_paths = []
    try:
        job = db.query(AssignmentGradingJob).filter_by(id=job_id).first()
        if job is None or job.status not in {"queued", "processing"}:
            return
        answers = db.query(AssignmentGradingAnswer).filter_by(job_id=job.id).all()
        questions = db.query(Question).filter(
            Question.assignment_id == job.assignment_id
        ).order_by(Question.order_num, Question.id).all()
        question_ids = {question.id for question in questions}
        answer_by_question = {answer.question_id: answer for answer in answers}
        if not questions or question_ids - set(answer_by_question):
            job.status = "failed"
            job.error = "作答内容不完整，请返回作业继续完成。"
            db.commit()
            return

        job.status = "processing"
        job.progress = 0
        job.total_questions = len(questions)
        job.error = None
        job.updated_at = datetime.now()
        db.commit()

        group_stems = {}
        group_rows = db.query(QuestionGroupMember.question_id, QuestionGroup.stem).join(
            QuestionGroup, QuestionGroup.id == QuestionGroupMember.group_id,
        ).filter(QuestionGroupMember.question_id.in_(question_ids)).all()
        group_stems = {question_id: stem for question_id, stem in group_rows}

        provider = get_provider()
        inferred_points = {}
        for question in questions:
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
        for subject in {question.subject for question in questions}:
            subject_questions = [question for question in questions if question.subject == subject]
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
            answer = answer_by_question[question.id]
            knowledge_point = inferred_points[question.id]
            rag_context = rag_by_subject.get(question.subject, "")
            if answer.image_path:
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
                diagnosis = provider.diagnose_homework_image(
                    image_bytes, content_type, context, knowledge_context=rag_context,
                )
                visual_steps = diagnosis.get("steps") or []
                source_image_path = source_path
                confidence = diagnosis.get("confidence", 0.5)
            else:
                student_work = [line.strip() for line in (answer.answer_text or "").splitlines()
                                if line.strip()]
                diagnosis = provider.diagnose_homework_text(
                    subject=question.subject,
                    question_text="\n".join(filter(None, (
                        group_stems.get(question.id), question.stem,
                        f"教师参考答案或步骤：{question.standard_answer or '未提供'}",
                    ))),
                    student_work=student_work,
                    knowledge_context=rag_context,
                )
                visual_steps = diagnosis.get("steps") or []
                source_image_path = None
                confidence = diagnosis.get("confidence", 0.5)
            if not visual_steps:
                raise ValueError(f"empty grading result for question {question.id}")
            grading_results.append((question, answer, knowledge_point, visual_steps,
                                    confidence, source_image_path))
            job.progress = index
            job.updated_at = datetime.now()
            db.commit()

        # 先完成整份作业的模型判断，再一次性写入提交，避免中途模型失败时只生成部分成绩。
        created_submissions = []
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
        for submission, _confidence, _visual_steps in created_submissions:
            review_svc.create_review_if_needed(db, submission, commit=False)
        job.status = "completed"
        job.progress = job.total_questions
        job.updated_at = datetime.now()
        db.commit()
        for answer in answers:
            if answer.image_path:
                image_paths_to_remove.append(_draft_image_path(answer.image_path))
    except Exception as exc:
        db.rollback()
        logger.warning("整份作业后台批改失败（job_id=%s, error=%s）", job_id, type(exc).__name__)
        job = db.query(AssignmentGradingJob).filter_by(id=job_id).first()
        if job is not None:
            job.status = "failed"
            job.error = "批改暂时失败，作答已保留，请点击重新批改。"
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
