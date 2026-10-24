# /api/teacher/* 教师端
import json
import logging
import os
import secrets
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload, load_only
from starlette.concurrency import run_in_threadpool

from ..auth import require_teacher
from ..config import settings
from ..database import get_db
from ..models import (
    Assignment,
    AssignmentExt,
    AssignmentScoring,
    AssignmentSetting,
    QuestionGroup,
    QuestionGroupMember,
    ChatMessage,
    ChatSession,
    ChatSessionMessage,
    ChatSessionMessageImage,
    ChatSessionMessageMistakeLink,
    AssignmentClass,
    Classroom,
    ClassroomMember,
    ClassroomTeacherSubject,
    Correction,
    Error,
    Essay,
    Notification,
    Question,
    QuestionWeight,
    Step,
    StudentMistakeArchive,
    StudentMistakeCategoryReview,
    StudentMistakeEvent,
    StudentQuestionCapture,
    Submission,
    SubmissionImage,
    SubmissionReview,
    SubmissionScore,
    SubjectKnowledgeChunk,
    SubjectKnowledgePassage,
    TeacherSubject,
    User,
    Verification,
    Workbook,
)
from ..schemas import (
    AgentChatIn,
    AgentHistoryItem,
    AgentHistoryPageOut,
    ChatSessionOut,
    ChatSessionPageOut,
    ClassRepairRateOut,
    ErrorTypeCountOut,
    ErrorCorrectIn,
    KnowledgePointRankItem,
    PhotoGroupTranscribeOut,
    PhotoTranscribeOut,
    ProfileOut,
    QuestionOut,
    RemindOut,
    ReviewApproveAllOut,
    ReviewApproveIn,
    ReviewApproveOut,
    ReviewDetailOut,
    ReviewPendingCountOut,
    ReviewPendingItem,
    ReviewPendingOut,
    ReviewScoreOut,
    StudentBrief,
    TeacherAssignmentCreate,
    TeacherAssignmentOut,
    TeacherAssignmentQuestionOut,
    TeacherDashboardOut,
    TeacherErrorItem,
    TopQuestionItem,
    UserOut,
    WorkbookExtractIn,
    WorkbookExtractOut,
    WorkbookOut,
    ClassroomCreateIn,
    ClassroomOut,
    ClassroomStudentCreateIn,
    ClassroomStudentOut,
    SubjectKnowledgeCreateIn,
    SubjectKnowledgeSearchIn,
)
from ..services import deferral as deferral_svc
from ..services import reviews as review_svc
from ..services.streaming import ClosingStreamingResponse
from ..services import scoring as scoring_svc
from ..services.answer_check import check_reference_answer
from ..services.diagnosis import (
    present_diagnosis_with_process_check,
    present_error,
)
from ..services.providers import get_provider
from ..services.stats import (
    class_repair_rate,
    knowledge_point_ranking,
    list_students,
    student_profile,
    top_error_questions,
)
from ..services.teacher_stats import students_not_fully_submitted
from ..services.teacher_scope import (
    teacher_assignment_ids as _scoped_teacher_assignment_ids,
    teacher_assignment_class_pairs as _scoped_teacher_assignment_class_pairs,
    teacher_assignment_question_ids as _scoped_teacher_assignment_question_ids,
    teacher_assignment_question_student_pairs as _scoped_teacher_assignment_question_student_pairs,
    teacher_essay_ids as _scoped_teacher_essay_ids,
    teacher_submission_ids as _scoped_teacher_submission_ids,
    teacher_student_ids as _scoped_teacher_student_ids,
)
from ..services.upload_files import delete_unreferenced_uploads

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
logger = logging.getLogger(__name__)

SUBJECT_LABELS = {
    "chinese": "语文", "math": "数学", "english": "英语", "politics": "道法",
    "history": "历史", "physics": "物理", "chemistry": "化学",
    "geography": "地理", "biology": "生物",
}


@router.get("/classes", response_model=List[ClassroomOut], summary="读取任教学科的班级名册")
def list_teacher_classes(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    rows = db.query(Classroom, ClassroomTeacherSubject.subject).join(
        ClassroomTeacherSubject, ClassroomTeacherSubject.classroom_id == Classroom.id,
    ).filter(ClassroomTeacherSubject.teacher_id == current.id).order_by(
        Classroom.name, Classroom.id, ClassroomTeacherSubject.subject,
    ).all()
    by_id = {}
    for classroom, subject in rows:
        item = by_id.setdefault(classroom.id, {
            "id": classroom.id, "name": classroom.name, "subjects": [], "student_count": 0,
        })
        item["subjects"].append(subject)
    for classroom_id, item in by_id.items():
        item["student_count"] = db.query(ClassroomMember.student_id).filter_by(
            classroom_id=classroom_id,
        ).count()
    return list(by_id.values())


@router.post("/classes", response_model=ClassroomOut, summary="建立或关联班级")
def create_or_link_classroom(
    body: ClassroomCreateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    if not db.query(TeacherSubject.teacher_id).filter_by(
        teacher_id=current.id, subject=body.subject,
    ).first():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先以该学科教师身份登录。")
    name = body.name.strip()
    classroom = db.query(Classroom).filter(Classroom.name == name).first()
    if classroom is None:
        classroom = Classroom(name=name, created_by=current.id)
        db.add(classroom)
        db.flush()
    mapping = db.query(ClassroomTeacherSubject).filter_by(
        classroom_id=classroom.id, teacher_id=current.id, subject=body.subject,
    ).first()
    if mapping is None:
        db.add(ClassroomTeacherSubject(
            classroom_id=classroom.id, teacher_id=current.id, subject=body.subject,
        ))
    db.commit()
    count = db.query(ClassroomMember.student_id).filter_by(classroom_id=classroom.id).count()
    subjects = [row[0] for row in db.query(ClassroomTeacherSubject.subject).filter_by(
        classroom_id=classroom.id, teacher_id=current.id,
    ).order_by(ClassroomTeacherSubject.subject).all()]
    return ClassroomOut(id=classroom.id, name=classroom.name, subjects=subjects, student_count=count)


@router.get("/classes/{classroom_id}/students", response_model=List[ClassroomStudentOut], summary="读取班级学生")
def list_classroom_students(
    classroom_id: int, db: Session = Depends(get_db), current: User = Depends(require_teacher),
):
    allowed = db.query(ClassroomTeacherSubject.classroom_id).filter_by(
        classroom_id=classroom_id, teacher_id=current.id,
    ).first()
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "班级不存在或你没有任课权限。")
    rows = db.query(User).join(ClassroomMember, ClassroomMember.student_id == User.id).filter(
        ClassroomMember.classroom_id == classroom_id, User.role == "student",
    ).order_by(User.student_no, User.id).all()
    return [ClassroomStudentOut(id=row.id, name=row.name, student_no=row.student_no or "") for row in rows]


@router.post("/classes/{classroom_id}/students", response_model=ClassroomStudentOut, summary="将学生录入班级名册")
def add_classroom_student(
    classroom_id: int,
    body: ClassroomStudentCreateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    allowed = db.query(ClassroomTeacherSubject.classroom_id).filter_by(
        classroom_id=classroom_id, teacher_id=current.id,
    ).first()
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "班级不存在或你没有任课权限。")
    name, student_no = body.name.strip(), body.student_no.strip()
    student = db.query(User).filter(User.student_no == student_no).first()
    if student is not None and (student.role != "student" or student.name != name):
        raise HTTPException(status.HTTP_409_CONFLICT, "学号已被其他学生占用，请核对名册。")
    if student is None:
        student = User(name=name, student_no=student_no, role="student")
        db.add(student)
        db.flush()
    membership = db.query(ClassroomMember).filter_by(
        classroom_id=classroom_id, student_id=student.id,
    ).first()
    if membership is None:
        db.add(ClassroomMember(classroom_id=classroom_id, student_id=student.id))
    db.commit()
    return ClassroomStudentOut(id=student.id, name=student.name, student_no=student.student_no)


def _require_teacher_subject(db: Session, teacher: User, subject: str) -> None:
    if not db.query(TeacherSubject.teacher_id).filter_by(
        teacher_id=teacher.id, subject=subject,
    ).first():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你没有该学科 Agent 的管理范围。")


@router.get("/knowledge/{subject}", summary="读取学科 Agent 的专属知识库")
def list_subject_knowledge(
    subject: str, db: Session = Depends(get_db), current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    _require_teacher_subject(db, current, subject)
    rows = db.query(SubjectKnowledgeChunk).filter(
        SubjectKnowledgeChunk.subject == subject,
    ).order_by(SubjectKnowledgeChunk.created_at.desc(), SubjectKnowledgeChunk.id.desc()).all()
    from ..services.rag_milvus import configured

    counts = dict(db.query(SubjectKnowledgePassage.document_id, func.count(SubjectKnowledgePassage.id)).join(
        SubjectKnowledgeChunk, SubjectKnowledgeChunk.id == SubjectKnowledgePassage.document_id,
    ).filter(SubjectKnowledgeChunk.subject == subject).group_by(SubjectKnowledgePassage.document_id).all())
    return {"subject": subject, "agent_name": SUBJECT_LABELS[subject], "total": len(rows),
            "vector_enabled": configured(), "items": [
        {"id": row.id, "title": row.title, "content": row.content,
         "source_name": row.source_name, "created_at": row.created_at,
         "passage_count": counts.get(row.id, 0)}
        for row in rows
    ]}


@router.post("/knowledge/{subject}", summary="向指定学科 Agent 知识库添加资料")
def add_subject_knowledge(
    subject: str,
    body: SubjectKnowledgeCreateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    _require_teacher_subject(db, current, subject)
    if not body.title.strip() or not body.content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "资料标题和内容不能为空。")
    from ..services.subject_rag import prepare_knowledge, sync_knowledge

    row = SubjectKnowledgeChunk(
        subject=subject, title=body.title.strip(), content=body.content.strip(),
        source_name=(body.source_name or "").strip() or None, created_by=current.id,
    )
    db.add(row)
    prepare_knowledge(db, row)
    db.commit()
    db.refresh(row)
    result = sync_knowledge(db, row.id)
    return {"id": row.id, "subject": row.subject, "title": row.title,
            "source_name": row.source_name, "created_at": row.created_at, **result}


@router.post("/knowledge/{subject}/import-pdf", summary="导入带文字层的学科教学 PDF")
async def import_subject_knowledge_pdf(
    subject: str, file: UploadFile = File(...),
    title: str = Form(default="", max_length=160),
    source_name: str = Form(default="", max_length=200),
    db: Session = Depends(get_db), current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    _require_teacher_subject(db, current, subject)
    from ..services.knowledge_import import MAX_PDF_BYTES, extract_knowledge_pdf
    from ..services.subject_rag import prepare_knowledge, sync_knowledge

    try:
        data = await file.read(MAX_PDF_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF 不能超过 20MB。")
    filename = (file.filename or "教学资料.pdf").replace("\\", "/").rsplit("/", 1)[-1]

    def save_pdf():
        try:
            extracted = extract_knowledge_pdf(data)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        row = SubjectKnowledgeChunk(
            subject=subject, title=title.strip() or filename[:160],
            content="\n\n".join(text for _, text in extracted["pages"]),
            source_name=source_name.strip() or filename[:200], created_by=current.id,
        )
        db.add(row)
        prepare_knowledge(db, row, pages=extracted["pages"])
        db.commit()
        db.refresh(row)
        result = sync_knowledge(db, row.id)
        return {"id": row.id, "subject": subject, "title": row.title,
                "source_name": row.source_name, "created_at": row.created_at,
                **result, "page_count": extracted["page_count"],
                "indexed_pages": extracted["indexed_pages"],
                "warnings": extracted["warnings"] + result.get("warnings", [])}

    return await run_in_threadpool(save_pdf)


@router.post("/knowledge/{subject}/search", summary="试查当前学科知识库并返回来源")
def search_subject_knowledge(
    subject: str, body: SubjectKnowledgeSearchIn,
    db: Session = Depends(get_db), current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    _require_teacher_subject(db, current, subject)
    if not body.query.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "检索问题不能为空。")
    from ..services.subject_rag import search_knowledge

    return search_knowledge(db, subject, body.query.strip(), body.limit)


@router.post("/knowledge/{subject}/reindex", summary="重建学科资料的 Milvus 检索索引")
def reindex_subject_knowledge(
    subject: str, db: Session = Depends(get_db), current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    _require_teacher_subject(db, current, subject)
    from ..services.subject_rag import reindex_subject

    result = reindex_subject(db, subject)
    db.commit()
    return result


@router.delete("/knowledge/{subject}/{chunk_id}", summary="删除学科 Agent 知识资料")
def delete_subject_knowledge(
    subject: str,
    chunk_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    if subject not in SUBJECT_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学科 Agent 不存在。")
    from ..services.subject_rag import delete_knowledge_index, delete_vector_index

    try:
        connection = db.connection()
        if connection.dialect.name == "sqlite":
            # Authentication may already have opened a SQLAlchemy transaction;
            # legacy sqlite3 SELECTs do not necessarily start a DB transaction.
            # Reserve the writer before reading the document, so its reusable
            # ID cannot be replaced between authorization and SQL deletion.
            if connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("UPDATE subject_knowledge_chunks SET id = id WHERE 0")
            else:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        _require_teacher_subject(db, current, subject)
        row = db.query(SubjectKnowledgeChunk).filter_by(
            id=chunk_id, subject=subject,
        ).with_for_update().first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "资料不存在。")
        deleted_passage_ids = delete_knowledge_index(db, row.id)
        db.delete(row)
        db.commit()
    except OperationalError as exc:
        db.rollback()
        error_code = getattr(exc.orig, "sqlite_errorcode", 0) or 0
        if error_code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise HTTPException(status.HTTP_409_CONFLICT, "资料正在变更，请稍后重试删除。") from exc
        raise
    except Exception:
        # Release the SQLite reservation on 403/404 as well as write failures.
        db.rollback()
        raise
    # Remote cleanup must never hold the local transaction's write lock.
    warnings = delete_vector_index(deleted_passage_ids)
    return {"deleted": True, "id": chunk_id, "subject": subject, "warnings": warnings}

ERROR_TYPES = ("计算失误", "概念混淆", "审题遗漏", "无法解析")


def _teacher_assignment_ids(db: Session, teacher: User):
    """教师只能读取自己发布或自己负责班级内对应学科的作业。"""
    return _scoped_teacher_assignment_ids(db, teacher)


def _teacher_student_ids(db: Session, teacher: User):
    return _scoped_teacher_student_ids(db, teacher)


def _teacher_submission_ids(db: Session, teacher: User):
    return _scoped_teacher_submission_ids(db, teacher)


def _require_teacher_assignment(db: Session, teacher: User, assignment_id: int) -> None:
    if not db.query(Assignment.id).filter(
        Assignment.id == assignment_id,
        Assignment.id.in_(_teacher_assignment_ids(db, teacher)),
    ).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在或你没有该学科的查看权限。")


def _require_teacher_submission(db: Session, teacher: User, submission_id: int) -> None:
    if not db.query(Submission.id).filter(
        Submission.id == submission_id,
        Submission.id.in_(_teacher_submission_ids(db, teacher)),
    ).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在或你没有该班级的查看权限。")


def _legacy_review_images(
    db: Session,
    submissions: List[Submission],
    images_by_submission: dict,
) -> dict:
    """批量回查旧版自主上传记录在聊天消息中保存的原图。"""
    candidates = [
        (sub.id, sub.student_id, sub.submitted_at)
        for sub in submissions
        if sub.id not in images_by_submission
        and sub.question is not None
        and sub.question.assignment is not None
        and sub.question.assignment.title.startswith("自主上传题目")
    ]
    if not candidates:
        return {}

    resolved_images = {}
    for start in range(0, len(candidates), 150):
        chunk = candidates[start:start + 150]
        matching_windows = or_(*[
            and_(
                ChatSession.user_id == student_id,
                ChatSessionMessage.role == "user",
                ChatSessionMessage.created_at <= submitted_at,
                ChatSessionMessage.created_at >= submitted_at - timedelta(minutes=15),
            )
            for _, student_id, submitted_at in chunk
        ])
        rows = (
            db.query(
                ChatSession.user_id,
                ChatSessionMessage.created_at,
                ChatSessionMessageImage,
            )
            .join(ChatSessionMessage, ChatSessionMessage.session_id == ChatSession.id)
            .join(
                ChatSessionMessageImage,
                ChatSessionMessageImage.message_id == ChatSessionMessage.id,
            )
            .filter(matching_windows)
            .order_by(
                ChatSession.user_id.asc(),
                ChatSessionMessage.created_at.asc(),
                ChatSessionMessage.id.asc(),
            )
            .all()
        )
        messages_by_student = defaultdict(list)
        for student_id, created_at, image in rows:
            messages_by_student[student_id].append((created_at, image))
        timestamps_by_student = {
            student_id: [created_at for created_at, _ in messages]
            for student_id, messages in messages_by_student.items()
        }

        for submission_id, student_id, submitted_at in chunk:
            messages = messages_by_student.get(student_id, [])
            index = bisect_right(
                timestamps_by_student.get(student_id, []), submitted_at
            ) - 1
            if index < 0:
                continue
            created_at, image = messages[index]
            if created_at >= submitted_at - timedelta(minutes=15):
                resolved_images[submission_id] = image
    return resolved_images


def _teacher_error_item(
    err: Error, db: Session, preloaded: Optional[dict] = None
) -> TeacherErrorItem:
    preloaded = preloaded or {}
    if "review_status" in preloaded:
        student = preloaded["student"]
        question = preloaded["question"]
        base = preloaded["base"]
        rstatus = preloaded["review_status"]
        vis = preloaded.get("visible_score")
    else:
        sub = db.query(Submission).filter(Submission.id == err.submission_id).first()
        student = db.query(User).filter(User.id == sub.student_id).first() if sub else None
        question = db.query(Question).filter(Question.id == sub.question_id).first() if sub else None
        base = present_error(err, db)
        rstatus = review_svc.review_status(db, err.submission_id)
        vis = None
        if rstatus != review_svc.PENDING and sub is not None:
            vis = scoring_svc.visible_score(db, sub)
    # 评分系统：已通过的条目带上最终分小标数据；待审核不给分（分数跟审核一起放行）
    score = max_score = None
    if vis:
        score, max_score = vis["score"], vis["max_score"]
    return TeacherErrorItem(
        id=base["id"],
        submission_id=err.submission_id,
        # v0.9.0：所属提交的审核状态，批改列表据此打「待审核」标并直达审核详情
        review_status=rstatus,
        score=score,
        max_score=max_score,
        student=UserOut.model_validate(student),
        question=QuestionOut.model_validate(question),
        step_seq=base["step_seq"],
        step_text=base["step_text"],
        knowledge_point=base["knowledge_point"],
        error_type=base["error_type"],
        confidence=base["confidence"],
        is_stubborn=base["is_stubborn"],
        detail=base["detail"],
        teacher_corrected=base["teacher_corrected"],
        teacher_note=base["teacher_note"],
        created_at=base["created_at"],
    )


@router.get("/errors", summary="错误记录列表")
def list_errors(
    error_id: Optional[int] = Query(default=None, ge=1),
    student_id: Optional[int] = Query(default=None),
    knowledge_point: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    stubborn_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    query = db.query(Error).join(
        Submission, Error.submission_id == Submission.id,
    ).join(
        Question, Question.id == Submission.question_id,
    ).filter(Submission.id.in_(_teacher_submission_ids(db, current)))
    if error_id is not None:
        query = query.filter(Error.id == error_id)
    if student_id:
        query = query.filter(Submission.student_id == student_id)
    if knowledge_point:
        query = query.filter(Error.knowledge_point == knowledge_point)
    if error_type:
        if error_type not in ERROR_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"error_type 非法，应为 {ERROR_TYPES}")
        query = query.filter(Error.error_type == error_type)
    if stubborn_only:
        query = query.filter(Error.is_stubborn.is_(True))
    query = query.outerjoin(
        SubmissionReview,
        SubmissionReview.submission_id == Error.submission_id,
    )
    page_rows = (
        query.options(
            load_only(
                Error.id, Error.submission_id, Error.step_id,
                Error.knowledge_point, Error.error_type, Error.confidence,
                Error.is_stubborn, Error.detail, Error.teacher_corrected,
                Error.teacher_note, Error.created_at,
            ),
            joinedload(Error.step).load_only(Step.id, Step.seq, Step.text),
            joinedload(Error.submission)
            .load_only(Submission.id, Submission.student_id, Submission.question_id)
            .options(
                joinedload(Submission.student).load_only(
                    User.id, User.name, User.student_no, User.role, User.created_at,
                ),
                joinedload(Submission.question).load_only(
                    Question.id, Question.assignment_id, Question.subject,
                    Question.knowledge_point, Question.stem, Question.order_num,
                ),
            ),
        )
        .add_columns(SubmissionReview.status.label("review_status"))
        .add_columns(func.count(Error.id).over().label("total"))
        .order_by(Error.created_at.desc(), Error.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    if page_rows:
        total = int(page_rows[0].total or 0)
        errs = []
        status_by_id = {}
        for error, review_status, _ in page_rows:
            errs.append(error)
            if review_status is not None:
                status_by_id[error.submission_id] = review_status
    else:
        # 窗口计数在空页没有返回行；仅此时单独查询总数以保留越界分页语义。
        total = query.count()
        errs = []
        status_by_id = {}
    submission_by_id = {
        err.submission_id: err.submission
        for err in errs
        if err.submission is not None
    }
    approved_submissions = [
        submission
        for submission_id, submission in submission_by_id.items()
        if status_by_id.get(submission_id, review_svc.APPROVED) != review_svc.PENDING
    ]
    preloaded_by_error_id = {}
    for err in errs:
        submission = submission_by_id.get(err.submission_id)
        step = err.step
        preloaded_by_error_id[err.id] = {
            "student": UserOut.model_validate(submission.student),
            "question": QuestionOut.model_validate(submission.question),
            "base": {
                "id": err.id,
                "step_seq": step.seq if step else None,
                "step_text": step.text if step else None,
                "knowledge_point": err.knowledge_point,
                "error_type": err.error_type,
                "confidence": err.confidence,
                "is_stubborn": err.is_stubborn,
                "detail": err.detail,
                "teacher_corrected": err.teacher_corrected,
                "teacher_note": err.teacher_note,
                "created_at": err.created_at,
            },
        }
    scores_by_id = scoring_svc.visible_scores(db, approved_submissions)
    items = []
    for err in errs:
        rstatus = status_by_id.get(err.submission_id, review_svc.APPROVED)
        items.append(_teacher_error_item(err, db, {
            **preloaded_by_error_id[err.id],
            "review_status": rstatus,
            "visible_score": scores_by_id.get(err.submission_id),
        }))
    return {"total": total, "items": items}


@router.get("/errors/summary", summary="最近错误记录轻量摘要")
def recent_error_summaries(
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    """教学建议页只需这些字段，避免执行完整批改列表的审核与成绩统计。"""
    rows = (
        db.query(
            Error.id,
            Error.knowledge_point,
            Error.error_type,
            Error.is_stubborn,
            User.id.label("student_id"),
            User.name.label("student_name"),
            Question.id.label("question_id"),
        )
        .join(Submission, Error.submission_id == Submission.id)
        .join(User, Submission.student_id == User.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(Submission.id.in_(_teacher_submission_ids(db, current)))
        .order_by(Error.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "knowledge_point": row.knowledge_point,
                "error_type": row.error_type,
                "is_stubborn": row.is_stubborn,
                "student": {"id": row.student_id, "name": row.student_name},
                "question": {"id": row.question_id},
            }
            for row in rows
        ]
    }


@router.post("/errors/{error_id}/correct", response_model=TeacherErrorItem, summary="教师一键纠错")
def correct_error(error_id: int, body: ErrorCorrectIn,
                  db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    row = (
        db.query(Error, SubmissionReview.status)
        .outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Error.submission_id,
        )
        .options(
            joinedload(Error.step),
            joinedload(Error.submission).joinedload(Submission.student),
            joinedload(Error.submission)
            .joinedload(Submission.question)
            .joinedload(Question.assignment),
        )
        .filter(Error.id == error_id)
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    err, review_status = row
    if err.submission is None or err.submission.question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    _require_teacher_submission(db, current, err.submission.id)
    old_type = err.error_type
    err.error_type = body.error_type
    err.teacher_note = body.teacher_note
    err.teacher_corrected = True
    # v0.3.0：纠错成功后给被纠错的学生写一条站内提醒（主流程：AI 初批 → 老师干预 → 学生收到提醒去订正）
    # 待审核期间先不额外发纠错提醒，避免重复打扰；教师通过时统一提醒学生查看更新后的诊断。
    sub = err.submission
    question = sub.question if sub is not None else None
    assignment = question.assignment if question is not None else None
    rstatus = (
        (review_status or review_svc.APPROVED)
        if sub is not None else review_svc.APPROVED
    )
    if sub is not None and rstatus != review_svc.PENDING:
        title = assignment.title if assignment else ""
        content = (
            f"{current.name}调整了你《{title}》的批改结果："
            f"错因由{old_type}改为{body.error_type}，点开看看老师的复核结果吧。"
        )
        db.add(Notification(
            user_id=sub.student_id,
            type="teacher_correction",
            content=content,
            related_submission_id=sub.id,
        ))
    if sub is not None and question is not None:
        from ..services.learning_memory import refresh_student_learning_memory
        refresh_student_learning_memory(
            db, sub.student_id, subject=question.subject,
            knowledge_point=err.knowledge_point, commit=False,
        )
    # 保留预加载关系，避免提交后为组装响应重新读取学生、题目和步骤。
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
        base = present_error(err, db, step=err.step)
        vis = (
            scoring_svc.visible_score(db, sub)
            if sub is not None and rstatus != review_svc.PENDING else None
        )
        return _teacher_error_item(err, db, {
            "student": sub.student if sub is not None else None,
            "question": question,
            "base": base,
            "review_status": rstatus,
            "visible_score": vis,
        })
    finally:
        db.expire_on_commit = expire_on_commit


# ---------- 提交审核（v0.9.0 新增）：低置信判断供教师复核，诊断与订正可并行 ----------

def _review_pending_item(
    sub: Submission,
    db: Session,
    assignment_context: Optional[Tuple[List[Submission], int, int]] = None,
    preloaded: Optional[dict] = None,
) -> ReviewPendingItem:
    preloaded = preloaded or {}
    student = sub.student
    question = sub.question
    assignment = question.assignment if question else None
    err_n = preloaded.get("error_count")
    if err_n is None:
        err_n = db.query(Error).filter(Error.submission_id == sub.id).count()
    step_statuses = preloaded.get("step_statuses")
    step_counts = preloaded.get("step_counts")
    if step_counts is not None:
        correct_steps, total_steps = step_counts
    elif step_statuses is None:
        answer_steps = db.query(Step).filter(Step.submission_id == sub.id).all()
        step_statuses = [step.status for step in answer_steps if (
            step.seq >= 1 and step.status in ("ok", "error", "unparseable")
        )]
        correct_steps, total_steps = scoring_svc.step_counts(answer_steps)
    else:
        step_statuses = list(step_statuses)
        correct_steps = sum(1 for value in step_statuses if value == "ok")
        total_steps = len(step_statuses)
    if assignment_context is None:
        assignment_context = review_svc.assignment_accuracy_context(db, sub)
    assignment_correct_steps = assignment_context[1] if assignment_context else 0
    assignment_total_steps = assignment_context[2] if assignment_context else 0
    score_context = preloaded.get("assignment_score_context")
    if score_context and score_context["complete"]:
        review_reasons = [
            f"整份作业得分低于 60 分（{score_context['score']}/{score_context['max_score']} 分）"
        ]
    else:
        review_reasons = ["整份作业结算得分低于 60 分"]
    submission_image = preloaded.get("submission_image")
    if submission_image is None and "submission_image" not in preloaded:
        submission_image = db.query(SubmissionImage).filter_by(submission_id=sub.id).first()
    image_url = f"/api/uploads/{submission_image.file_path}" if submission_image else None
    image_name = submission_image.file_name if submission_image else None
    # 兼容关联表新增之前的自主上传记录：当时原图只挂在学生对话消息上，
    # 用该学生提交前 15 分钟内最近一张图片补出缩略图。
    if (
        image_url is None
        and assignment
        and assignment.title.startswith("自主上传题目")
        and not preloaded.get("legacy_image_lookup_complete")
    ):
        legacy_image = (
            db.query(ChatSessionMessageImage)
            .join(ChatSessionMessage, ChatSessionMessage.id == ChatSessionMessageImage.message_id)
            .join(ChatSession, ChatSession.id == ChatSessionMessage.session_id)
            .filter(
                ChatSession.user_id == sub.student_id,
                ChatSessionMessage.role == "user",
                ChatSessionMessage.created_at <= sub.submitted_at,
                ChatSessionMessage.created_at >= sub.submitted_at - timedelta(minutes=15),
            )
            .order_by(ChatSessionMessage.created_at.desc())
            .first()
        )
        if legacy_image:
            image_url = f"/api/uploads/{legacy_image.file_path}"
            image_name = legacy_image.file_name
    return ReviewPendingItem(
        submission_id=sub.id,
        student=UserOut.model_validate(student),
        assignment_id=assignment.id if assignment else None,
        assignment_title=assignment.title if assignment else "",
        question_id=question.id if question else 0,
        question_stem=question.stem if question else "",
        subject=question.subject if question else "",
        knowledge_point=question.knowledge_point if question else "",
        error_count=err_n,
        correct_steps=correct_steps,
        total_steps=total_steps,
        assignment_correct_steps=assignment_correct_steps,
        assignment_total_steps=assignment_total_steps,
        review_reason="；".join(review_reasons),
        submitted_at=sub.submitted_at,
        image_url=image_url,
        image_name=image_name,
    )


@router.get("/reviews/pending/count", response_model=ReviewPendingCountOut,
            summary="待审核数量（导航角标）")
def reviews_pending_count(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    subs = review_svc.pending_reviews(db, submission_ids=_teacher_submission_ids(db, current))
    count, latest_submission_id = len(subs), max((sub.id for sub in subs), default=None)
    return {
        "count": int(count or 0),
        "latest_submission_id": latest_submission_id,
    }


@router.get("/reviews/pending", response_model=ReviewPendingOut, summary="待审核队列（v0.9.0 新增）")
def reviews_pending(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """审核页待审核提交列表（按提交时间正序）及其总数。"""
    subs = review_svc.pending_reviews(db, submission_ids=_teacher_submission_ids(db, current))
    submission_ids = [sub.id for sub in subs]
    step_counts_by_submission = {}
    error_summaries_by_submission = {}
    images_by_submission = {}
    for start in range(0, len(submission_ids), 500):
        submission_id_chunk = submission_ids[start:start + 500]
        queue_submission_ids = (
            db.query(SubmissionReview.submission_id.label("submission_id"))
            .filter(SubmissionReview.submission_id.in_(submission_id_chunk))
            .cte("queue_submission_ids")
        )
        step_counts = (
            db.query(
                Step.submission_id.label("submission_id"),
                func.sum(case((Step.status == "ok", 1), else_=0)).label(
                    "correct_steps"
                ),
                func.count(Step.id).label("total_steps"),
            )
            .join(
                queue_submission_ids,
                queue_submission_ids.c.submission_id == Step.submission_id,
            )
            .filter(
                Step.seq >= 1,
                Step.status.in_(("ok", "error", "unparseable")),
            )
            .group_by(Step.submission_id)
            .subquery()
        )
        error_summaries = (
            db.query(
                Error.submission_id.label("submission_id"),
                func.count(Error.id).label("error_count"),
            )
            .join(
                queue_submission_ids,
                queue_submission_ids.c.submission_id == Error.submission_id,
            )
            .group_by(Error.submission_id)
            .subquery()
        )
        summary_rows = db.query(
            Submission.id,
            step_counts.c.correct_steps,
            step_counts.c.total_steps,
            error_summaries.c.error_count,
            SubmissionImage,
        ).join(
            queue_submission_ids,
            queue_submission_ids.c.submission_id == Submission.id,
        ).outerjoin(
            step_counts,
            step_counts.c.submission_id == Submission.id,
        ).outerjoin(
            error_summaries,
            error_summaries.c.submission_id == Submission.id,
        ).outerjoin(
            SubmissionImage,
            SubmissionImage.submission_id == Submission.id,
        ).all()
        for (
            submission_id,
            correct_steps,
            total_steps,
            error_count,
            image,
        ) in summary_rows:
            step_counts_by_submission[submission_id] = (
                int(correct_steps or 0), int(total_steps or 0)
            )
            error_summaries_by_submission[submission_id] = int(error_count or 0)
            if image is not None:
                images_by_submission[submission_id] = image
    legacy_images_by_submission = _legacy_review_images(db, subs, images_by_submission)
    assignment_contexts = review_svc.assignment_accuracy_contexts(db, subs)
    score_contexts = review_svc.assignment_score_contexts(db, subs)
    items = []
    for sub in subs:
        question = sub.question
        if question is None:
            assignment_context = None
        else:
            key = (sub.student_id, question.assignment_id)
            assignment_context = assignment_contexts.get(key)
        error_count = error_summaries_by_submission.get(sub.id, 0)
        score_context = (
            score_contexts.get((sub.student_id, question.assignment_id))
            if question is not None else None
        )
        preloaded = {
            "step_counts": step_counts_by_submission.get(sub.id, (0, 0)),
            "error_count": error_count,
            "assignment_score_context": score_context,
            "submission_image": (
                images_by_submission.get(sub.id)
                or legacy_images_by_submission.get(sub.id)
            ),
            "legacy_image_lookup_complete": True,
        }
        items.append(_review_pending_item(sub, db, assignment_context, preloaded))
    return {
        "count": len(items),
        "items": items,
        "latest_submission_id": max(submission_ids, default=None),
    }


@router.post("/reviews/approve-all", response_model=ReviewApproveAllOut, summary="全部通过审核（v0.9.0 新增）")
def reviews_approve_all(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """把当前队列里全部 pending 提交置为 approved，逐个给学生发审核通过提醒。
    评分系统：通过时一并落定最终分（未改分 = AI 初评分）。"""
    subs = review_svc.pending_reviews(db, submission_ids=_teacher_submission_ids(db, current))
    approved_ids = set()
    if subs:
        approved_ids = review_svc.approve_submissions(db, subs, current)
        approved_subs = [sub for sub in subs if sub.id in approved_ids]
        scoring_svc.finalize_on_approve_many(db, approved_subs, current)
        db.commit()
        from ..services.learning_memory import refresh_student_learning_memory
        for sub in subs:
            if sub.id in approved_ids and sub.question is not None:
                refresh_student_learning_memory(
                    db, sub.student_id, subject=sub.question.subject,
                    knowledge_point=sub.question.knowledge_point,
                )
    return {"approved_count": len(approved_ids)}


@router.get("/reviews/{submission_id}", response_model=ReviewDetailOut, summary="审核详情（v0.9.0 新增）")
def review_detail(submission_id: int, db: Session = Depends(get_db),
                  current: User = Depends(require_teacher)):
    """一份提交的完整 AI 分步诊断（教师端全量可见）+ 审核状态，供审核详情页复核与纠错。"""
    row = (
        db.query(Submission, SubmissionReview.status)
        .outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        )
        .options(
            joinedload(Submission.student).load_only(
                User.id, User.name, User.student_no, User.role, User.created_at,
            ),
            joinedload(Submission.question)
            .load_only(
                Question.id, Question.assignment_id, Question.subject,
                Question.knowledge_point, Question.stem, Question.order_num,
            )
            .joinedload(Question.assignment)
            .load_only(Assignment.id, Assignment.title),
        )
        .filter(Submission.id == submission_id)
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    sub, review_status = row
    if sub.question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    _require_teacher_submission(db, current, sub.id)
    student = sub.student
    question = sub.question
    assignment = question.assignment if question else None
    steps = (
        db.query(Step)
        .filter(Step.submission_id == sub.id)
        .order_by(Step.seq)
        .all()
    )
    diagnosis, process_check = present_diagnosis_with_process_check(
        sub, db, steps=steps, strict_process_check=True
    )
    rstatus = review_status or review_svc.APPROVED
    diagnosis["review_status"] = rstatus
    # 评分系统：本题满分/AI 分/步骤明细，老师据此核对分数、决定是否改分
    score_info = scoring_svc.score_detail_for_teacher(db, sub, steps=steps)
    return ReviewDetailOut(
        submission_id=sub.id,
        student=UserOut.model_validate(student),
        assignment_title=assignment.title if assignment else "",
        question=QuestionOut.model_validate(question),
        submitted_at=sub.submitted_at,
        review_status=rstatus,
        diagnosis=diagnosis,
        score=ReviewScoreOut(**score_info),
        process_check=process_check,
    )


@router.post("/reviews/{submission_id}/approve", response_model=ReviewApproveOut, summary="审核通过（v0.9.0 新增）")
def review_approve(submission_id: int, body: Optional[ReviewApproveIn] = None,
                   db: Session = Depends(get_db),
                   current: User = Depends(require_teacher)):
    """通过一份提交的 AI 批改结果：置 approved 并给学生发提醒。
    幂等：已通过的重复调用不重复发提醒。改错因走既有的一键纠错接口，保存后再调本接口即「改后通过」。
    评分系统：body 可带 final_score（老师改分，须在 0~本题满分之间）；不带 = 用 AI 初评分落定最终分。"""
    sub = db.query(Submission).options(
        joinedload(Submission.question)
        .load_only(Question.id, Question.assignment_id)
        .joinedload(Question.assignment)
        .load_only(Assignment.id, Assignment.title)
    ).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    if sub.question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    _require_teacher_submission(db, current, sub.id)
    if body is not None and body.final_score is not None:
        max_score = scoring_svc.question_max_score(db, sub.question) if sub.question else 0.0
        if body.final_score > max_score:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"分数不能超过本题满分 {max_score:g}",
            )
    submission_id = sub.id
    review_svc.approve_submission(db, sub, current, commit=False)
    scoring_svc.finalize_on_approve(
        db, sub, current,
        final_score=body.final_score if body is not None else None,
        commit=False,
    )
    db.commit()
    if sub.question is not None:
        review_svc.refresh_assignment_review(db, sub)
    return {"submission_id": submission_id, "review_status": "approved"}


@router.get("/stats/top-questions", summary="高频错题 TopN")
def stats_top_questions(n: int = Query(default=10, ge=1, le=50),
                        db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    items = top_error_questions(
        db, n, assignment_ids, submission_ids=_teacher_submission_ids(db, current),
    )
    return {"n": n, "items": [TopQuestionItem(**it) for it in items]}


@router.get("/stats/knowledge-points", summary="知识点错误率排行")
def stats_knowledge_points(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    items = knowledge_point_ranking(
        db, assignment_ids, submission_ids=_teacher_submission_ids(db, current),
    )
    return {"items": [KnowledgePointRankItem(**it) for it in items]}


@router.get("/stats/repair-rate", response_model=ClassRepairRateOut, summary="班级知识修复率（v0.4.0 新增）")
def stats_repair_rate(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """班级知识修复率 + 各知识点修复率：口径与学生学习报告四态一致
    （全部错题订正正确，且最新错题之后通过二次验证）。"""
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    student_ids = [row[0] for row in _teacher_student_ids(db, current).all()]
    submission_ids = _teacher_submission_ids(db, current)
    return class_repair_rate(db, student_ids, assignment_ids, submission_ids)


@router.get("/dashboard", response_model=TeacherDashboardOut, summary="教师首页看板汇总")
def teacher_dashboard(
    n: int = Query(default=10, ge=1, le=50),
    include_suggestions: bool = Query(default=False),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    """一次返回教师首页各卡片数据，错因分布只读取最近 100 条的类别字段。"""
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    student_ids = [row[0] for row in _teacher_student_ids(db, current).all()]
    authorized_submission_ids = _teacher_submission_ids(db, current)
    error_total, stubborn_total = db.query(
        func.count(Error.id),
        func.sum(case((Error.is_stubborn.is_(True), 1), else_=0)),
    ).join(Submission, Error.submission_id == Submission.id).join(
        Question, Question.id == Submission.question_id,
    ).filter(
        Question.assignment_id.in_(assignment_ids),
        Submission.id.in_(authorized_submission_ids),
    ).one()
    graded_submissions, graded_submissions_with_errors = db.query(
        func.count(func.distinct(Submission.id)),
        func.count(func.distinct(Error.submission_id)),
    ).outerjoin(
        Error, Error.submission_id == Submission.id,
    ).filter(
        Submission.status == "graded",
        Submission.id.in_(authorized_submission_ids),
        Submission.question_id.in_(db.query(Question.id).filter(
            Question.assignment_id.in_(assignment_ids),
        )),
    ).one()

    recent_error_types = db.query(
        Error.error_type.label("error_type")
    ).join(
        Submission, Error.submission_id == Submission.id,
    ).join(
        Question, Question.id == Submission.question_id,
    ).filter(
        Question.assignment_id.in_(assignment_ids),
        Submission.id.in_(authorized_submission_ids),
    ).order_by(
        Error.created_at.desc()
    ).limit(100).subquery()
    counts_by_type = dict(db.query(
        recent_error_types.c.error_type,
        func.count(),
    ).group_by(recent_error_types.c.error_type).all())

    # 建议生成也需要前 50 道高频题；一次取回并复用统计结果，避免重复执行聚合查询。
    top_question_rows = top_error_questions(
        db,
        max(n, 50) if include_suggestions else n,
        assignment_ids,
        submission_ids=authorized_submission_ids,
    )
    knowledge_point_rows = knowledge_point_ranking(
        db, assignment_ids, submission_ids=authorized_submission_ids,
    )
    top_questions = [
        TopQuestionItem(**item) for item in top_question_rows[:n]
    ]
    knowledge_points = [
        KnowledgePointRankItem(**item) for item in knowledge_point_rows
    ]
    students_list = [StudentBrief(**item) for item in list_students(
        db, student_ids=student_ids, assignment_ids=assignment_ids,
    )]

    repair_rate_data = None
    try:
        repair_rate_data = class_repair_rate(
            db, student_ids, assignment_ids, authorized_submission_ids,
        )
        repair_rate = ClassRepairRateOut(**repair_rate_data)
    except Exception:
        # 和旧看板单独请求修复率时的降级口径一致：该卡为空值，其余统计仍可展示。
        db.rollback()
        logger.exception("教师首页班级知识修复率统计失败")
        repair_rate = None

    suggestions = None
    if include_suggestions:
        try:
            from ..services.suggestions import build_teaching_suggestions

            suggestions = build_teaching_suggestions(db, precomputed_stats={
                "repair_rate": repair_rate_data or {},
                "knowledge_points": knowledge_point_rows,
                "top_questions": top_question_rows,
                "assignment_ids": assignment_ids,
                "student_ids": student_ids,
                "submission_ids": authorized_submission_ids,
            })
        except Exception:
            logger.exception("教师首页教学建议生成失败")
            suggestions = []

    return TeacherDashboardOut(
        top_questions=top_questions,
        knowledge_points=knowledge_points,
        students=students_list,
        total_errors=int(error_total or 0),
        stubborn_errors=int(stubborn_total or 0),
        graded_submissions=int(graded_submissions or 0),
        graded_submissions_with_errors=int(graded_submissions_with_errors or 0),
        repair_rate=repair_rate,
        recent_error_types=[
            ErrorTypeCountOut(name=name, value=count)
            for name, count in counts_by_type.items()
        ],
        suggestions=suggestions,
    )


@router.get("/students", summary="学生列表")
def students(
    steady_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    allowed_ids = [row[0] for row in _teacher_student_ids(db, current).all()]
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    items = list_students(
        db, steady_only=steady_only,
        student_ids=allowed_ids, assignment_ids=assignment_ids,
    )
    return {"total": len(items), "items": [StudentBrief(**it) for it in items]}


@router.get("/students/{student_id}/profile", response_model=ProfileOut, summary="学生画像查询")
def student_profile_view(student_id: int, db: Session = Depends(get_db),
                         current: User = Depends(require_teacher)):
    st = db.query(User).filter(User.id == student_id, User.role == "student").first()
    if not st:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生不存在")
    if not db.query(ClassroomTeacherSubject.classroom_id).join(
        ClassroomMember, ClassroomMember.classroom_id == ClassroomTeacherSubject.classroom_id,
    ).filter(
        ClassroomTeacherSubject.teacher_id == current.id,
        ClassroomMember.student_id == student_id,
    ).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生不存在或你没有该班级的查看权限。")
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    return student_profile(
        db, st, assignment_ids=assignment_ids,
        submission_ids=_teacher_submission_ids(db, current),
    )


# ---------- 发布作业（v0.2.0 新增） ----------

# ---------- 参考答案 AI 验算（v0.9.3 新增） ----------

class AnswerCheckIn(BaseModel):
    stem: str = Field(min_length=1, max_length=2000)             # 题干
    reference_answer: str = Field(min_length=1, max_length=2000)  # 教师填写的参考答案
    knowledge_point: Optional[str] = Field(default=None, max_length=64)


class AnswerCheckOut(BaseModel):
    status: str  # ok（验算无误）| suspect（疑似有误，仅警告）| unknown（无法自动验算）
    detail: str  # 一句中文说明
    method: str  # sympy | llm | none


@router.post("/questions/check-answer", response_model=AnswerCheckOut,
             summary="参考答案 AI 验算（v0.9.3 新增）")
def check_answer(body: AnswerCheckIn, current: User = Depends(require_teacher)):
    """发布前帮教师验算自己填的参考答案：先走 sympy 代入/求解验算，判不了
    再问一次 LLM。只警告、永不拦截发布；任何异常都收敛为 unknown 返回。"""
    result = check_reference_answer(body.stem, body.reference_answer, body.knowledge_point)
    return AnswerCheckOut(**result)


class KnowledgePointGuessIn(BaseModel):
    prompt: str  # 题干


class KnowledgePointGuessOut(BaseModel):
    knowledge_point: str  # 猜到的知识点名；判不出为空串


@router.post("/questions/guess-knowledge-point", response_model=KnowledgePointGuessOut,
             summary="按题干 AI 识别知识点（v0.13.0 新增）")
def guess_knowledge_point(body: KnowledgePointGuessIn,
                          current: User = Depends(require_teacher)):
    """发布页知识点栏的 AI 识别：文本模型按题干判断知识点名（无模型时走关键词
    启发式兜底）。结果只是建议、教师可改；判不出返回空串。本接口不落库。"""
    stem = (body.prompt or "").strip()
    if not stem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "先填写题干，再用 AI 识别知识点。")
    return KnowledgePointGuessOut(knowledge_point=get_provider().guess_knowledge_point(stem))


def _teacher_assignments_out(
    assignments: List[Assignment], db: Session, teacher: User,
    submission_ids=None, essay_ids=None, question_ids=None,
    visible_class_pairs=None,
) -> List[TeacherAssignmentOut]:
    """批量组装教师作业列表，避免逐作业、逐题查询统计和配置。"""
    if not assignments:
        return []

    def id_chunks(ids: List[int], size: int = 500):
        for start in range(0, len(ids), size):
            yield ids[start:start + size]

    assignment_ids = [assignment.id for assignment in assignments]
    class_ids_by_assignment = defaultdict(list)
    for assignment_id, classroom_id in db.query(
        AssignmentClass.assignment_id, AssignmentClass.classroom_id,
    ).filter(AssignmentClass.assignment_id.in_(assignment_ids)).all():
        if (
            visible_class_pairs is None
            or (assignment_id, classroom_id) in visible_class_pairs
        ):
            class_ids_by_assignment[assignment_id].append(classroom_id)
    questions = []
    weights = {}
    for assignment_id_chunk in id_chunks(assignment_ids):
        question_query = (
            db.query(Question, QuestionWeight.weight_pct)
            .outerjoin(
                QuestionWeight,
                QuestionWeight.question_id == Question.id,
            )
            .filter(Question.assignment_id.in_(assignment_id_chunk))
        )
        if question_ids is not None:
            question_query = question_query.filter(Question.id.in_(question_ids))
        for question, weight_pct in question_query.order_by(
            Question.assignment_id, Question.order_num, Question.id,
        ).all():
            questions.append(question)
            if weight_pct is not None:
                weights[question.id] = float(weight_pct)
    # 各批次查询已按作业、题目顺序和 ID 排序；同一作业不会跨批次，
    # 后续按作业分组时保留该顺序即可，无需再次全局排序全部题目。
    question_ids = [question.id for question in questions]
    question_counts = {}
    for question in questions:
        question_counts[question.assignment_id] = (
            question_counts.get(question.assignment_id, 0) + 1
        )

    submission_counts = {}
    for question_id_chunk in id_chunks(question_ids):
        submission_student_query = db.query(
            Submission.question_id.label("question_id"),
            Submission.student_id.label("student_id"),
        ).filter(Submission.question_id.in_(question_id_chunk))
        essay_student_query = db.query(
            Essay.question_id.label("question_id"),
            Essay.student_id.label("student_id"),
        ).filter(Essay.question_id.in_(question_id_chunk))
        if submission_ids is not None:
            submission_student_query = submission_student_query.filter(
                Submission.id.in_(submission_ids)
            )
        if essay_ids is not None:
            essay_student_query = essay_student_query.filter(Essay.id.in_(essay_ids))
        activity_pairs = submission_student_query.union(
            essay_student_query
        ).subquery()
        count_rows = db.query(
            activity_pairs.c.question_id,
            func.count(activity_pairs.c.student_id).label("submission_count"),
        ).group_by(activity_pairs.c.question_id).subquery()
        submission_counts.update(dict(
            db.query(
                count_rows.c.question_id,
                func.sum(count_rows.c.submission_count),
            )
            .group_by(count_rows.c.question_id)
            .all()
        ))
    extensions = {}
    settings_by_assignment = {}
    total_scores = {}
    workbook_titles = {}
    for assignment_id_chunk in id_chunks(assignment_ids):
        config_rows = (
            db.query(
                AssignmentExt,
                AssignmentSetting,
                AssignmentScoring,
                Workbook.title,
            )
            .select_from(Assignment)
            .outerjoin(
                AssignmentExt,
                AssignmentExt.assignment_id == Assignment.id,
            )
            .outerjoin(
                AssignmentSetting,
                AssignmentSetting.assignment_id == Assignment.id,
            )
            .outerjoin(
                AssignmentScoring,
                AssignmentScoring.assignment_id == Assignment.id,
            )
            .outerjoin(Workbook, Workbook.id == AssignmentExt.workbook_id)
            .filter(Assignment.id.in_(assignment_id_chunk))
            .all()
        )
        for extension, setting, scoring, workbook_title in config_rows:
            if extension is not None:
                extensions[extension.assignment_id] = extension
                if extension.workbook_id and workbook_title is not None:
                    workbook_titles[extension.workbook_id] = workbook_title
            if setting is not None:
                settings_by_assignment[setting.assignment_id] = setting
            if scoring is not None:
                total_scores[scoring.assignment_id] = (
                    float(scoring.total_score) if scoring.total_score else 100.0
                )

    questions_by_assignment = {}
    for question in questions:
        questions_by_assignment.setdefault(question.assignment_id, []).append(question)

    result = []
    for assignment in assignments:
        question_items = []
        count_for_assignment = question_counts.get(assignment.id, 0)
        for question in questions_by_assignment.get(assignment.id, []):
            weight_pct = weights.get(
                question.id, 100.0 / count_for_assignment if count_for_assignment else 100.0
            )
            question_items.append(TeacherAssignmentQuestionOut(
                id=question.id,
                type="math" if question.subject == "math" else "essay",
                subject=question.subject,
                prompt=question.stem,
                knowledge_point=question.knowledge_point,
                standard_answer=question.standard_answer,
                submission_count=submission_counts.get(question.id, 0),
                weight_pct=round(weight_pct, 2),
            ))

        extension = extensions.get(assignment.id)
        setting = settings_by_assignment.get(assignment.id)
        result.append(TeacherAssignmentOut(
            id=assignment.id,
            title=assignment.title,
            description=assignment.description,
            created_at=assignment.created_at,
            questions=question_items,
            mode=(extension.mode or "online") if extension else "online",
            workbook_title=(
                workbook_titles.get(extension.workbook_id)
                if extension and extension.workbook_id else None
            ),
            page_range=extension.page_range if extension else None,
            deadline=extension.deadline if extension else None,
            total_score=total_scores.get(assignment.id, 100.0),
            allow_revision=bool(setting.allow_revision) if setting else False,
            class_ids=class_ids_by_assignment.get(assignment.id, []),
            can_delete=assignment.created_by == teacher.id,
        ))
    return result


@router.post("/assignments", response_model=TeacherAssignmentOut, summary="发布作业")
def create_assignment(body: TeacherAssignmentCreate,
                      db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """创建一份作业并落库，学生端立即可见。
    standard_steps 无独立存储列：落库时并入 standard_answer（参考答案优先）。
    v0.5.0：mode=offline 时把 mode/workbook_id/page_range/deadline 写进 assignment_ext；
    workbook_id 必须指向本人上传的练习册。"""
    workbook = None
    assignment_deadline = deferral_svc.normalize_deadline(body.deadline)
    class_ids = sorted(set(body.class_ids))
    if not class_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "发布作业前请先建立班级并选择接收班级。")
    question_subjects = {
        q.subject or ("math" if q.type == "math" else "english")
        for q in body.questions
    }
    for subject in question_subjects:
        _require_teacher_subject(db, current, subject)
    mapped_pairs = set(db.query(
        ClassroomTeacherSubject.classroom_id,
        ClassroomTeacherSubject.subject,
    ).filter(
        ClassroomTeacherSubject.teacher_id == current.id,
        ClassroomTeacherSubject.classroom_id.in_(class_ids),
        ClassroomTeacherSubject.subject.in_(question_subjects),
    ).all())
    missing_pairs = [
        (class_id, subject)
        for class_id in class_ids for subject in question_subjects
        if (class_id, subject) not in mapped_pairs
    ]
    if missing_pairs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "所选班级没有关联当前作业的全部学科，请检查班级任课设置。",
        )
    if body.mode == "offline" and body.workbook_id is not None:
        workbook = (
            db.query(Workbook)
            .filter(Workbook.id == body.workbook_id, Workbook.teacher_id == current.id)
            .first()
        )
        if not workbook:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选练习册不存在或不是你上传的")
    assignment = Assignment(
        title=body.title, description=body.description, created_by=current.id,
    )
    db.add(assignment)
    db.flush()  # 拿到 assignment.id
    created_questions = []
    for i, q in enumerate(body.questions, start=1):
        standard_answer = q.reference_answer
        if not standard_answer and q.standard_steps:
            standard_answer = "\n".join(s.strip() for s in q.standard_steps if s.strip())
        question = Question(
            assignment_id=assignment.id,
            # 逐题 subject 是新增字段；旧客户端仍按 type 映射数学/英语，
            # 保留旧作业混合 math/essay 题型的兼容行为。
            subject=q.subject or ("math" if q.type == "math" else "english"),
            knowledge_point=q.knowledge_point,
            stem=q.prompt,
            standard_answer=standard_answer,
            order_num=i,
        )
        db.add(question)
        created_questions.append((question, q.weight_pct))
    db.flush()  # 拿到各 question.id
    # 评分系统：总分与每题分值占比落库（新表）；没传的项不写行，走默认口径
    scoring_svc.set_assignment_scoring(
        db, assignment.id, body.total_score,
        [(q.id, pct) for q, pct in created_questions],
        is_new=True,
    )
    # v0.13.1：ext 行恒建（mode + deadline 两种模式都落，线上作业此前没 ext 行、
    # 截止时间会被静默丢弃）；练习册/页码仅线下有
    db.add(AssignmentExt(
        assignment_id=assignment.id,
        mode=body.mode,
        workbook_id=workbook.id if (body.mode == "offline" and workbook) else None,
        page_range=((body.page_range or "").strip() or None) if body.mode == "offline" else None,
        deadline=assignment_deadline,
    ))
    for classroom_id in class_ids:
        db.add(AssignmentClass(assignment_id=assignment.id, classroom_id=classroom_id))
    # v0.13.1：提交设置（允许修改）与大题分组
    if body.allow_revision:
        db.add(AssignmentSetting(assignment_id=assignment.id, allow_revision=True))
    created_groups = []
    for gi, g in enumerate(body.groups, start=1):
        grp = QuestionGroup(assignment_id=assignment.id, stem=g.stem, order_num=gi)
        db.add(grp)
        created_groups.append((g.key, grp))
    if created_groups:
        db.flush()
    group_id_by_key = {key: grp.id for key, grp in created_groups}
    for (question, _pct), qin in zip(created_questions, body.questions):
        if qin.group_key and qin.group_key in group_id_by_key:
            db.add(QuestionGroupMember(question_id=question.id, group_id=group_id_by_key[qin.group_key]))
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit

    question_count = len(created_questions)
    return TeacherAssignmentOut(
        id=assignment.id,
        title=assignment.title,
        description=assignment.description,
        created_at=assignment.created_at,
        questions=[
            TeacherAssignmentQuestionOut(
                id=question.id,
                type="math" if question.subject == "math" else "essay",
                subject=question.subject,
                prompt=question.stem,
                knowledge_point=question.knowledge_point,
                standard_answer=question.standard_answer,
                submission_count=0,
                weight_pct=round(
                    float(weight_pct) if weight_pct is not None
                    else 100.0 / question_count,
                    2,
                ),
            )
            for question, weight_pct in created_questions
        ],
        mode=body.mode,
        workbook_title=workbook.title if body.mode == "offline" and workbook else None,
        page_range=(
            ((body.page_range or "").strip() or None)
            if body.mode == "offline" else None
        ),
        deadline=assignment_deadline,
        total_score=float(body.total_score) if body.total_score is not None else 100.0,
        allow_revision=body.allow_revision,
        class_ids=class_ids,
        can_delete=True,
    )


@router.get("/assignments", summary="已发布作业列表")
def list_teacher_assignments(
    created_on: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    query = db.query(Assignment).filter(
        Assignment.id.in_(_teacher_assignment_ids(db, current)),
    )
    if created_on is not None:
        day_start = datetime.combine(created_on, datetime.min.time())
        query = query.filter(
            Assignment.created_at >= day_start,
            Assignment.created_at < day_start + timedelta(days=1),
        )
    assignments = query.order_by(Assignment.id).all()
    visible_class_pairs = {
        (assignment_id, classroom_id)
        for assignment_id, classroom_id in _scoped_teacher_assignment_class_pairs(
            db, current, [assignment.id for assignment in assignments],
        ).all()
    }
    items = _teacher_assignments_out(
        assignments,
        db,
        current,
        submission_ids=_teacher_submission_ids(db, current),
        essay_ids=_scoped_teacher_essay_ids(db, current),
        question_ids=_scoped_teacher_assignment_question_ids(
            db, current, [assignment.id for assignment in assignments],
        ),
        visible_class_pairs=visible_class_pairs,
    )
    return {"total": len(items), "items": items}


@router.get("/assignments/calendar-marks", summary="教师作业日历标记")
def teacher_assignment_calendar_marks(
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    """Return daily assignment counts used by the right-rail calendar."""
    created_on = func.date(Assignment.created_at)
    rows = (
        db.query(
            created_on.label("created_on"),
            func.count(Assignment.id).label("assignment_count"),
        )
        .group_by(created_on)
        .filter(Assignment.id.in_(_teacher_assignment_ids(db, current)))
        .all()
    )
    return {
        str(day): int(count or 0)
        for day, count in rows
        if day is not None
    }


def _delete_unreferenced_submission_images(db: Session, file_paths: set[str]) -> None:
    delete_unreferenced_uploads(
        db, file_paths, reason="作业删除后"
    )


def _trace_assignment_delete_failures(handler):
    """保留删除请求的服务端异常上下文，并给教师可关联的错误编号。"""
    @wraps(handler)
    def wrapped(assignment_id: int, db: Session = Depends(get_db),
                current: User = Depends(require_teacher)):
        try:
            return handler(assignment_id, db, current)
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            incident_id = secrets.token_hex(4)
            logger.exception(
                "教师删除作业失败 (assignment_id=%s, incident_id=%s, error_type=%s)",
                assignment_id,
                incident_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"删除失败，错误编号 {incident_id}，请稍后重试。",
            ) from exc
    return wrapped


@router.delete("/assignments/{assignment_id}", summary="删除已发布作业")
@_trace_assignment_delete_failures
def delete_assignment(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_teacher)):
    """仅发布者可以删除作业，防止共享作业的任课教师误删其他班级数据。
    事务内按外键依赖顺序级联删除：
    corrections → notifications（关联这些提交的）→ errors → steps → submissions
    → essays → questions → assignment，避免孤儿数据污染学生报告与班级统计。
    不存在返回 404。与错题关联的二次验证保留并解除来源关联；学生自主上传题留档保留并解除题目关联。"""
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id)
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    _require_teacher_assignment(db, current, assignment_id)
    if assignment.created_by != current.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在或你没有删除权限。")
    question_ids = select(Question.id).where(Question.assignment_id == assignment.id)
    submission_ids = (
        select(Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .where(Question.assignment_id == assignment.id)
    )
    error_ids = (
        select(Error.id)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .where(Question.assignment_id == assignment.id)
    )
    submission_image_paths = {
        file_path
        for file_path, in db.query(SubmissionImage.file_path)
        .filter(SubmissionImage.submission_id.in_(submission_ids))
        .all()
        if file_path
    }
    db.query(ChatSessionMessageMistakeLink).filter(
        ChatSessionMessageMistakeLink.error_id.in_(error_ids)
    ).delete(synchronize_session=False)
    db.query(Verification).filter(
        Verification.source_error_id.in_(error_ids)
    ).update({Verification.source_error_id: None}, synchronize_session=False)
    db.query(Correction).filter(Correction.error_id.in_(error_ids)) \
        .delete(synchronize_session=False)
    db.query(StudentMistakeArchive).filter(
        StudentMistakeArchive.error_id.in_(error_ids)
    ).delete(synchronize_session=False)
    db.query(Notification).filter(
        Notification.related_submission_id.in_(submission_ids)
    ).delete(synchronize_session=False)
    # v0.9.0：审核行随提交一并清理，避免待审核队列出现孤儿
    db.query(SubmissionReview).filter(
        SubmissionReview.submission_id.in_(submission_ids)
    ).delete(synchronize_session=False)
    # 评分系统：得分行随提交一并清理
    db.query(SubmissionScore).filter(
        SubmissionScore.submission_id.in_(submission_ids)
    ).delete(synchronize_session=False)
    db.query(SubmissionImage).filter(
        SubmissionImage.submission_id.in_(submission_ids)
    ).delete(synchronize_session=False)
    db.query(Error).filter(Error.submission_id.in_(submission_ids)) \
        .delete(synchronize_session=False)
    db.query(Step).filter(Step.submission_id.in_(submission_ids)) \
        .delete(synchronize_session=False)
    db.query(Submission).filter(Submission.question_id.in_(question_ids)) \
        .delete(synchronize_session=False)
    db.query(Essay).filter(Essay.question_id.in_(question_ids)) \
        .delete(synchronize_session=False)
    # 学生上传题的原始留档独立于作业，保留图片与识别文本，只解除已删除题目的关联。
    db.query(StudentQuestionCapture).filter(
        StudentQuestionCapture.question_id.in_(question_ids)
    ).update({StudentQuestionCapture.question_id: None}, synchronize_session=False)
    # 评分系统：题目分值占比行随题目一并清理
    db.query(QuestionWeight).filter(QuestionWeight.question_id.in_(question_ids)) \
        .delete(synchronize_session=False)
    # v0.13.1：大题成员行随题目一并清理
    db.query(QuestionGroupMember).filter(QuestionGroupMember.question_id.in_(question_ids)) \
        .delete(synchronize_session=False)
    db.query(Question).filter(Question.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    # v0.13.1：提交设置行与大题行随作业一并清理
    db.query(AssignmentSetting).filter(AssignmentSetting.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    db.query(QuestionGroup).filter(QuestionGroup.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    # v0.5.0：作业扩展行（发布模式/练习册关联）一并删除
    db.query(AssignmentExt).filter(AssignmentExt.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    # 评分系统：作业分值设置行一并删除
    db.query(AssignmentScoring).filter(AssignmentScoring.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    db.query(AssignmentClass).filter(
        AssignmentClass.assignment_id == assignment.id,
    ).delete(synchronize_session=False)
    # 错题本学习/归档状态随作业一并清理，避免留下孤儿记录
    db.query(StudentMistakeCategoryReview).filter(StudentMistakeCategoryReview.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    db.query(StudentMistakeEvent).filter(StudentMistakeEvent.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    db.delete(assignment)
    db.commit()
    _delete_unreferenced_submission_images(db, submission_image_paths)
    return {"deleted": True}


@router.post("/assignments/{assignment_id}/remind", response_model=RemindOut,
             summary="一键提醒未交学生（v0.5.0 新增）")
def remind_assignment(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_teacher)):
    """给「还没提交全部题目」的学生各写一条站内提醒（便利贴通知），
    只提醒作业接收名单中且在教师任教范围内的未全交学生。"""
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id)
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    _require_teacher_assignment(db, current, assignment_id)
    question_student_pairs = _scoped_teacher_assignment_question_student_pairs(
        db, current, assignment_id,
    )
    student_ids = question_ids = None
    if question_student_pairs is None:
        # Legacy assignments without recipient classes still need the caller's
        # classroom and subject scope before the reminder can fan out.
        student_ids = [row[0] for row in _teacher_student_ids(db, current).all()]
        question_ids = _scoped_teacher_assignment_question_ids(
            db, current, [assignment_id],
        )
    targets = students_not_fully_submitted(
        db, assignment, student_ids=student_ids,
        question_student_pairs=question_student_pairs, question_ids=question_ids,
    )
    for student_id in targets:
        db.add(Notification(
            user_id=student_id,
            type="teacher_reminder",
            content=f"{current.name}提醒你：《{assignment.title}》还没有完成，记得及时提交哦",
            related_submission_id=None,
        ))
    db.commit()
    return {"reminded_count": len(targets)}


# ---------- 练习册知识库（v0.5.0 新增） ----------

_WORKBOOK_MAX_BYTES = 30 * 1024 * 1024
_WORKBOOK_SUBDIR = "workbooks"


def _write_uploaded_file(path: str, data: bytes) -> None:
    with open(path, "wb") as uploaded_file:
        uploaded_file.write(data)


def _workbook_out(w: Workbook, with_cover: bool = False) -> WorkbookOut:
    """练习册出参；with_cover 时走 services.covers 的懒生成（封面缺失补渲染一次）。"""
    cover = None
    if with_cover:
        from ..services.covers import ensure_cover

        cover = ensure_cover(w.id, w.file_path)
    else:
        from ..services.covers import cover_url

        cover = cover_url(w.id)
    return WorkbookOut(
        id=w.id,
        title=w.title,
        file_url=f"/api/uploads/{w.file_path}",
        cover_url=cover,
        created_at=w.created_at,
    )


@router.post("/workbooks", response_model=WorkbookOut, summary="上传练习册 PDF")
async def upload_workbook(file: UploadFile = File(...),
                          db: Session = Depends(get_db),
                          current: User = Depends(require_teacher)):
    """上传整本练习册 PDF 存入知识库（UPLOAD_DIR/workbooks/），发布线下作业时可直接选用。
    仅 PDF、≤30MB；标题默认取文件名（去扩展名），文件只存盘、元信息落 workbooks 表。"""
    filename = (file.filename or "").strip()
    is_pdf = file.content_type == "application/pdf" or filename.lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只支持上传 PDF 文件")
    data = await file.read(_WORKBOOK_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空，请重新上传")
    if len(data) > _WORKBOOK_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF 大小不能超过 30MB")
    target_dir = os.path.join(settings.UPLOAD_DIR, _WORKBOOK_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)
    stored_name = "{}_{}.pdf".format(
        datetime.now().strftime("%Y%m%d%H%M%S"), secrets.token_hex(4)
    )
    target_path = os.path.join(target_dir, stored_name)
    await run_in_threadpool(_write_uploaded_file, target_path, data)
    base = os.path.splitext(os.path.basename(filename))[0].strip()
    w = Workbook(
        teacher_id=current.id,
        title=base or "未命名练习册",
        file_path=f"{_WORKBOOK_SUBDIR}/{stored_name}",
    )
    db.add(w)
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            os.remove(target_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                "练习册元信息保存失败后清理 PDF 文件失败（file_path=%s）",
                target_path,
                exc_info=True,
            )
        raise
    finally:
        db.expire_on_commit = expire_on_commit
    # v0.6.0：上传成功后尝试把 PDF 第一页渲染成封面图（失败静默跳过，前端用书脊兜底）
    from ..services.covers import generate_cover

    await run_in_threadpool(
        generate_cover, w.id, os.path.join(settings.UPLOAD_DIR, w.file_path)
    )
    return _workbook_out(w)


@router.get("/workbooks", summary="我的练习册知识库")
def list_workbooks(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    rows = (
        db.query(Workbook)
        .filter(Workbook.teacher_id == current.id)
        .order_by(Workbook.created_at.desc(), Workbook.id.desc())
        .all()
    )
    return {"total": len(rows), "items": [_workbook_out(w, with_cover=True) for w in rows]}


@router.delete("/workbooks/{workbook_id}", summary="删除练习册")
def delete_workbook(workbook_id: int, db: Session = Depends(get_db),
                    current: User = Depends(require_teacher)):
    """删除本人上传的一本练习册（连同 PDF 文件）。已被线下作业引用的也可删除：
    对应 assignment_ext.workbook_id 置空，作业本身与其余信息保留。非本人/不存在统一 404。"""
    w = (
        db.query(Workbook)
        .filter(Workbook.id == workbook_id, Workbook.teacher_id == current.id)
        .first()
    )
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "练习册不存在")
    pdf_path = os.path.join(settings.UPLOAD_DIR, w.file_path)
    from ..services.covers import cover_file_path

    cover_path = cover_file_path(w.id)
    db.query(AssignmentExt).filter(AssignmentExt.workbook_id == w.id) \
        .update({AssignmentExt.workbook_id: None}, synchronize_session=False)
    db.delete(w)
    db.commit()
    for file_path in (pdf_path, cover_path):
        try:
            os.remove(file_path)
        except FileNotFoundError:
            continue
        except OSError:
            # 数据库删除已提交；清理失败只留孤立文件，不应把删除显示成失败。
            logger.warning(
                "练习册删除后清理文件失败（file_path=%s）",
                file_path,
                exc_info=True,
            )
    return {"deleted": True}


@router.post("/workbooks/{workbook_id}/extract-questions",
             response_model=WorkbookExtractOut, summary="从练习册 PDF 指定页自动识别题目")
def extract_workbook_questions(workbook_id: int, body: WorkbookExtractIn,
                               db: Session = Depends(get_db),
                               current: User = Depends(require_teacher)):
    """按页提题（v0.13.0）：解析 body.page_range 的页码 → 把这些页渲染成图 →
    视觉模型逐页拆题 → 返回草稿题列表（带来源页）。只读操作：不落库、不发布，
    前端把草稿填入题目卡，教师检查修改后才随作业一起发布。
    渲染与页码解析是纯程序处理；拆题走视觉模型（见 services/pdf_extract.py）。"""
    w = (
        db.query(Workbook)
        .filter(Workbook.id == workbook_id, Workbook.teacher_id == current.id)
        .first()
    )
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "练习册不存在")
    from ..services.pdf_extract import extract_questions_from_workbook

    try:
        return extract_questions_from_workbook(w.file_path, body.page_range)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


# ---------- 教师 AI 助手（v0.5.0 新增，LangGraph；v0.6.0 改会话制，口径与学生端一致） ----------

_AGENT_MSG_MAX = 2000
_AGENT_HISTORY_WINDOW = 20
_AGENT_HISTORY_RETURN = 50


@router.get("/agent/sessions", response_model=List[ChatSessionOut], summary="教师对话会话列表（v0.6.0 新增）")
def teacher_agent_sessions(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """历史对话列表：按最近更新倒序，含消息数。首次访问触发旧 chat_messages 迁移。"""
    from ..services import chat_sessions as cs

    return cs.list_sessions(db, current)


@router.get("/agent/sessions/page", response_model=ChatSessionPageOut,
            summary="分页读取教师对话会话")
def teacher_agent_session_page(
    limit: int = Query(default=50, ge=1, le=100),
    before_updated_at: Optional[datetime] = Query(default=None),
    before_id: Optional[int] = Query(default=None, ge=1),
    include_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    if (before_updated_at is None) != (before_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "before_updated_at 和 before_id 必须同时提供",
        )
    from ..services import chat_sessions as cs

    return cs.list_sessions_page(
        db, current, limit, before_updated_at, before_id, include_id
    )


@router.post("/agent/sessions", response_model=ChatSessionOut, summary="新建教师对话会话（v0.6.0 新增）")
def teacher_agent_create_session(db: Session = Depends(get_db),
                                 current: User = Depends(require_teacher)):
    """新建一条空会话并成为当前会话（标题先给「新对话」，首条消息到达时自动改标题）。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    s = cs.create_session(db, current)
    return {"id": s.id, "title": s.title, "created_at": s.created_at,
            "updated_at": s.updated_at, "message_count": 0}


@router.get("/agent/sessions/{session_id}/messages", response_model=List[AgentHistoryItem],
            summary="某会话的全部消息（v0.6.0 新增）")
def teacher_agent_session_messages(session_id: int, db: Session = Depends(get_db),
                                   current: User = Depends(require_teacher)):
    """会话内全部消息时间正序；会话不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    session = cs.get_own_session_or_migrate(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in cs.session_messages(db, session)
    ]


@router.get("/agent/sessions/{session_id}/messages/page",
            response_model=AgentHistoryPageOut,
            summary="分页读取某会话消息")
def teacher_agent_session_message_page(
    session_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    before_created_at: Optional[datetime] = Query(default=None),
    before_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    """按时间倒序取一页，并按时间正序返回；较早历史用游标继续读取。"""
    if (before_created_at is None) != (before_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "before_created_at 和 before_id 必须同时提供",
        )
    from ..services import chat_sessions as cs

    session = cs.get_own_session_or_migrate(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    page, has_more, cursor_created_at, cursor_id = cs.session_message_page(
        db,
        session,
        limit,
        before_created_at,
        before_id,
    )
    return {
        "items": [
            {"role": message.role, "content": message.content,
             "created_at": message.created_at}
            for message in page
        ],
        "has_more": has_more,
        "before_created_at": cursor_created_at,
        "before_id": cursor_id,
    }


@router.delete("/agent/sessions/{session_id}", summary="删除一条教师对话会话（v0.6.0 新增）")
def teacher_agent_delete_session(session_id: int, db: Session = Depends(get_db),
                                 current: User = Depends(require_teacher)):
    """删除本人的一条会话及其全部消息；不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    if not cs.delete_session(db, current, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return {"deleted": True}


@router.post("/agent/chat", summary="已停用：请使用班级数据助理流式接口")
def teacher_agent_chat_legacy(current: User = Depends(require_teacher)):
    raise HTTPException(status.HTTP_410_GONE, "此接口已停用，请改用 /api/teacher/agent/chat/stream")


@router.post("/agent/chat/stream", summary="与班级数据助理流式对话")
def teacher_agent_chat_stream(body: AgentChatIn, db: Session = Depends(get_db),
                              current: User = Depends(require_teacher)):
    """以 SSE 逐块返回教师助手回复；模型失败时发送错误事件，不生成模拟答案。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from ..agent.suggestions import teacher_suggestions
    from ..agent.teacher_graph import teacher_agent_reply_stream
    from ..services import chat_sessions as cs

    text = body.message.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "消息不能为空")
    if len(text) > _AGENT_MSG_MAX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "消息有点长，单条最多 2000 字，请分开发送")

    session, rows = cs.resolve_chat_session_history(
        db, current, body.session_id, _AGENT_HISTORY_WINDOW
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")

    history = [
        HumanMessage(content=row.content) if row.role == "user" else AIMessage(content=row.content)
        for row in rows
    ]
    if body.persist_user_message:
        cs.append_message(db, session, "user", text)

    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def stream_events():
        yield ": connected\n\n"
        reply_stream = teacher_agent_reply_stream(db, current, history, text)
        try:
            while True:
                try:
                    chunk = next(reply_stream)
                except StopIteration as stopped:
                    result = stopped.value
                    break
                yield event("token", {"text": chunk})

            reply = result["reply"]
            cs.append_message(db, session, "assistant", reply)
            yield event("done", {
                "reply": reply,
                "suggestions": teacher_suggestions(text, result.get("tools_used")),
                "session_id": session.id,
            })
        except Exception:
            logger.exception("教师班级数据助理流式回复中断")
            yield event("error", {"detail": "模型暂时无法回复，请稍后重试。"})
        finally:
            reply_stream.close()

    return ClosingStreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agent/history", response_model=List[AgentHistoryItem], summary="教师对话历史")
def teacher_agent_history(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """兼容旧用法：返回「当前会话」最近 50 条消息（v0.6.0 起按会话隔离）。"""
    from ..services import chat_sessions as cs

    session = cs.current_session_or_migrate(db, current)
    if session is None:
        return []
    return [
        AgentHistoryItem(role=m.role, content=m.content, created_at=m.created_at)
        for m in cs.session_messages(db, session, limit=_AGENT_HISTORY_RETURN)
    ]


@router.post("/agent/new-session", response_model=ChatSessionOut, summary="开始新对话（v0.6.0 改为新建会话）")
def teacher_agent_new_session(db: Session = Depends(get_db),
                              current: User = Depends(require_teacher)):
    """「新对话」（v0.6.0 语义变更）：新建一条会话并设为当前，旧会话保留在历史
    列表里可找回（取代 v0.5.0 的物理删除口径，不再删任何东西）。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    s = cs.create_session(db, current)
    return {"id": s.id, "title": s.title, "created_at": s.created_at,
            "updated_at": s.updated_at, "message_count": 0}


# ---------- 拍照识别题目（v0.2.1 新增） ----------

_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp"}
_PHOTO_MAX_BYTES = 10 * 1024 * 1024


@router.post("/photo-recognize", response_model=PhotoTranscribeOut, summary="拍照识别题目")
async def photo_recognize(file: UploadFile = File(...),
                          save_image: bool = Query(
                              default=True,
                              description="是否保存原图并返回可回读地址；默认保存",
                          ),
                          current: User = Depends(require_teacher)):
    """上传题目照片并转写，默认返回图片回读信息，save_image=false 时跳过保存。
    规则与学生端 photo-transcribe 一致（jpg/png/webp、≤10MB）；
    前端把 question_text 填入题干、steps 填入标准步骤，教师检查修改后再发布。
    注意：v1 直接复用学生作答转写能力（transcribe_image），未针对题目照片单独调 prompt。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read(_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    result = await run_in_threadpool(
        get_provider().transcribe_image, data, file.content_type
    )
    image_id = image_url = None
    if save_image:
        image_id = "{}_{}{}".format(
            datetime.now().strftime("%Y%m%d%H%M%S"),
            secrets.token_hex(4),
            _PHOTO_TYPES[file.content_type],
        )
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        await run_in_threadpool(
            _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, image_id), data
        )
        image_url = f"/api/uploads/{image_id}"
    return {
        "image_id": image_id,
        "image_url": image_url,
        "question_text": result.get("question_text", ""),
        "steps": result.get("steps", []),
    }


@router.post("/photo-recognize-group", response_model=PhotoGroupTranscribeOut, summary="拍照识别大题")
async def photo_recognize_group(file: UploadFile = File(...),
                                save_image: bool = Query(
                                    default=True,
                                    description="是否保存原图并返回可回读地址；默认保存",
                                ),
                                current: User = Depends(require_teacher)):
    """上传大题照片 → Provider 视觉识别 → 返回 {stem, sub_questions}（v0.13.11）。

    识别入口在大题层级：一张图一次拆出共同题干与全部小题（照片里有解题过程
    才带每道小题的 steps），前端据此新建/填充一个大题，教师检查修改后再发布；
    不再逐个小题拍照识别。图片规则与单题识别一致（jpg/png/webp、≤10MB）；
    save_image=false 时只返回识别结果，不持久化原图。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read(_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    result = await run_in_threadpool(
        get_provider().transcribe_group_image, data, file.content_type
    )
    image_id = image_url = None
    if save_image:
        image_id = "{}_{}{}".format(
            datetime.now().strftime("%Y%m%d%H%M%S"),
            secrets.token_hex(4),
            _PHOTO_TYPES[file.content_type],
        )
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        await run_in_threadpool(
            _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, image_id), data
        )
        image_url = f"/api/uploads/{image_id}"
    return {
        "image_id": image_id,
        "image_url": image_url,
        "stem": result.get("stem", ""),
        "sub_questions": result.get("sub_questions", []),
    }


# ---------- 教学建议（规则模板生成，只读统计不调 LLM） ----------

@router.get("/suggestions", summary="教学建议：下节课讲什么/哪些知识点要预警")
def teaching_suggestions(db: Session = Depends(get_db),
                         current: User = Depends(require_teacher)):
    """根据班级修复率、知识点错误率、顽固错题与成绩聚合，用规则模板生成教学建议卡。

    每条 {kind, title, knowledge_point, evidence, action, sample_questions}，按严重度排序、最多 6 条；
    数据不足返回空列表。生成逻辑在 services/suggestions.py，异常已在服务层收敛，不会 500。"""
    from ..services.suggestions import build_teaching_suggestions
    assignment_ids = [row[0] for row in _teacher_assignment_ids(db, current).all()]
    student_ids = [row[0] for row in _teacher_student_ids(db, current).all()]
    submission_ids = _teacher_submission_ids(db, current)
    return build_teaching_suggestions(db, precomputed_stats={
        "repair_rate": class_repair_rate(
            db, student_ids, assignment_ids, submission_ids,
        ),
        "knowledge_points": knowledge_point_ranking(
            db, assignment_ids, submission_ids=submission_ids,
        ),
        "top_questions": top_error_questions(
            db, 50, assignment_ids, submission_ids=submission_ids,
        ),
        "assignment_ids": assignment_ids,
        "student_ids": student_ids,
        "submission_ids": submission_ids,
    })
