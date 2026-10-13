# /api/teacher/* 教师端
import json
import logging
import os
import secrets
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

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
    User,
    Verification,
    Workbook,
)
from ..schemas import (
    AgentChatIn,
    AgentHistoryItem,
    ChatSessionOut,
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
)
from ..services import reviews as review_svc
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

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
logger = logging.getLogger(__name__)

ERROR_TYPES = ("计算失误", "概念混淆", "审题遗漏", "无法解析")


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
    student_id: Optional[int] = Query(default=None),
    knowledge_point: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    stubborn_only: bool = Query(default=False),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    query = db.query(Error).join(Submission, Error.submission_id == Submission.id)
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
    page_rows = (
        query.options(
            joinedload(Error.step),
            joinedload(Error.submission).joinedload(Submission.student),
            joinedload(Error.submission).joinedload(Submission.question),
        )
        .add_columns(func.count(Error.id).over().label("total"))
        .order_by(Error.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    if page_rows:
        total = int(page_rows[0].total or 0)
        errs = [error for error, _ in page_rows]
    else:
        # 窗口计数在空页没有返回行；仅此时单独查询总数以保留越界分页语义。
        total = query.count()
        errs = []
    submission_by_id = {
        err.submission_id: err.submission
        for err in errs
        if err.submission is not None
    }
    status_by_id = review_svc.review_status_map(db, submission_by_id)
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


@router.post("/errors/{error_id}/correct", response_model=TeacherErrorItem, summary="教师一键纠错")
def correct_error(error_id: int, body: ErrorCorrectIn,
                  db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    err = (
        db.query(Error)
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
    if not err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
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
        review_svc.review_status(db, sub.id)
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
    if step_statuses is None:
        answer_steps = db.query(Step).filter(Step.submission_id == sub.id).all()
        correct_steps, total_steps = scoring_svc.step_counts(answer_steps)
    else:
        correct_steps = sum(1 for value in step_statuses if value == "ok")
        total_steps = len(step_statuses)
    if assignment_context is None:
        assignment_context = review_svc.assignment_accuracy_context(db, sub)
    assignment_correct_steps = assignment_context[1] if assignment_context else 0
    assignment_total_steps = assignment_context[2] if assignment_context else 0
    review_reasons = review_svc.review_reasons(
        db,
        sub,
        assignment_context=assignment_context,
        step_statuses=step_statuses,
        error_confidences=preloaded.get("error_confidences"),
    )
    if not review_reasons:
        # 当前待审记录没有低步骤率或低错因置信度时，来源是视觉模型判断置信度。
        review_reasons = ["图片或步骤判断置信度低于 60%"]
    submission_image = preloaded.get("submission_image")
    if submission_image is None and "submission_image" not in preloaded:
        submission_image = db.query(SubmissionImage).filter_by(submission_id=sub.id).first()
    image_url = f"/api/uploads/{submission_image.file_path}" if submission_image else None
    image_name = submission_image.file_name if submission_image else None
    # 兼容关联表新增之前的自主上传记录：当时原图只挂在学生对话消息上，
    # 用该学生提交前 15 分钟内最近一张图片补出缩略图。
    if image_url is None and assignment and assignment.title.startswith("自主上传题目"):
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
    count = db.query(func.count(SubmissionReview.submission_id)).filter(
        SubmissionReview.status == review_svc.PENDING
    ).scalar()
    return {"count": int(count or 0)}


@router.get("/reviews/pending", response_model=ReviewPendingOut, summary="待审核队列（v0.9.0 新增）")
def reviews_pending(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """审核页待审核提交列表（按提交时间正序）及其总数。"""
    subs = review_svc.pending_reviews(db)
    submission_ids = [sub.id for sub in subs]
    step_statuses_by_submission = defaultdict(list)
    error_confidences_by_submission = defaultdict(list)
    images_by_submission = {}
    for start in range(0, len(submission_ids), 500):
        submission_id_chunk = submission_ids[start:start + 500]
        for submission_id, step_status in db.query(Step.submission_id, Step.status).filter(
            Step.submission_id.in_(submission_id_chunk),
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).all():
            step_statuses_by_submission[submission_id].append(step_status)
        for submission_id, confidence in db.query(Error.submission_id, Error.confidence).filter(
            Error.submission_id.in_(submission_id_chunk)
        ).all():
            error_confidences_by_submission[submission_id].append(float(confidence))
        images_by_submission.update({
            image.submission_id: image
            for image in db.query(SubmissionImage).filter(
                SubmissionImage.submission_id.in_(submission_id_chunk)
            ).all()
        })
    legacy_images_by_submission = _legacy_review_images(db, subs, images_by_submission)
    assignment_contexts = review_svc.assignment_accuracy_contexts(db, subs)
    items = []
    for sub in subs:
        question = sub.question
        if question is None:
            assignment_context = None
        else:
            key = (sub.student_id, question.assignment_id)
            assignment_context = assignment_contexts.get(key)
        preloaded = {
            "step_statuses": step_statuses_by_submission[sub.id],
            "error_confidences": error_confidences_by_submission[sub.id],
            "error_count": len(error_confidences_by_submission[sub.id]),
            "submission_image": (
                images_by_submission.get(sub.id)
                or legacy_images_by_submission.get(sub.id)
            ),
        }
        items.append(_review_pending_item(sub, db, assignment_context, preloaded))
    return {"count": len(items), "items": items}


@router.post("/reviews/approve-all", response_model=ReviewApproveAllOut, summary="全部通过审核（v0.9.0 新增）")
def reviews_approve_all(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """把当前队列里全部 pending 提交置为 approved，逐个给学生发审核通过提醒。
    评分系统：通过时一并落定最终分（未改分 = AI 初评分）。"""
    subs = review_svc.pending_reviews(db)
    if subs:
        scoring_svc.finalize_on_approve_many(db, subs, current)
        review_svc.approve_submissions(db, subs, current)
        db.commit()
    return {"approved_count": len(subs)}


@router.get("/reviews/{submission_id}", response_model=ReviewDetailOut, summary="审核详情（v0.9.0 新增）")
def review_detail(submission_id: int, db: Session = Depends(get_db),
                  current: User = Depends(require_teacher)):
    """一份提交的完整 AI 分步诊断（教师端全量可见）+ 审核状态，供审核详情页复核与纠错。"""
    sub = (
        db.query(Submission)
        .options(
            joinedload(Submission.student),
            joinedload(Submission.question).joinedload(Question.assignment),
        )
        .filter(Submission.id == submission_id)
        .first()
    )
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
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
    rstatus = review_svc.review_status(db, sub.id)
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
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    if body is not None and body.final_score is not None:
        max_score = scoring_svc.question_max_score(db, sub.question) if sub.question else 0.0
        if body.final_score > max_score:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"分数不能超过本题满分 {max_score:g}",
            )
    review_svc.approve_submission(db, sub, current)
    scoring_svc.finalize_on_approve(
        db, sub, current,
        final_score=body.final_score if body is not None else None,
    )
    return {"submission_id": sub.id, "review_status": "approved"}


@router.get("/stats/top-questions", summary="高频错题 TopN")
def stats_top_questions(n: int = Query(default=10, ge=1, le=50),
                        db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = top_error_questions(db, n)
    return {"n": n, "items": [TopQuestionItem(**it) for it in items]}


@router.get("/stats/knowledge-points", summary="知识点错误率排行")
def stats_knowledge_points(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = knowledge_point_ranking(db)
    return {"items": [KnowledgePointRankItem(**it) for it in items]}


@router.get("/stats/repair-rate", response_model=ClassRepairRateOut, summary="班级知识修复率（v0.4.0 新增）")
def stats_repair_rate(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """班级知识修复率 + 各知识点修复率：口径与学生学习报告四态一致
    （已修复 = 错题订正后通过二次验证）。"""
    return class_repair_rate(db)


@router.get("/dashboard", response_model=TeacherDashboardOut, summary="教师首页看板汇总")
def teacher_dashboard(
    n: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    """一次返回教师首页各卡片数据，错因分布只读取最近 100 条的类别字段。"""
    error_total, stubborn_total = db.query(
        func.count(Error.id),
        func.sum(case((Error.is_stubborn.is_(True), 1), else_=0)),
    ).join(Submission, Error.submission_id == Submission.id).one()

    recent_error_types = db.query(Error.error_type).join(
        Submission, Error.submission_id == Submission.id,
    ).order_by(Error.created_at.desc()).limit(100).all()
    counts_by_type = {}
    for (error_type,) in recent_error_types:
        counts_by_type[error_type] = counts_by_type.get(error_type, 0) + 1

    top_questions = [
        TopQuestionItem(**item) for item in top_error_questions(db, n)
    ]
    knowledge_points = [
        KnowledgePointRankItem(**item) for item in knowledge_point_ranking(db)
    ]
    students_list = [StudentBrief(**item) for item in list_students(db)]

    try:
        repair_rate = ClassRepairRateOut(**class_repair_rate(db))
    except Exception:
        # 和旧看板单独请求修复率时的降级口径一致：该卡为空值，其余统计仍可展示。
        db.rollback()
        logger.exception("教师首页班级知识修复率统计失败")
        repair_rate = None

    return TeacherDashboardOut(
        top_questions=top_questions,
        knowledge_points=knowledge_points,
        students=students_list,
        total_errors=int(error_total or 0),
        stubborn_errors=int(stubborn_total or 0),
        repair_rate=repair_rate,
        recent_error_types=[
            ErrorTypeCountOut(name=name, value=count)
            for name, count in counts_by_type.items()
        ],
    )


@router.get("/students", summary="学生列表")
def students(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = list_students(db)
    return {"total": len(items), "items": [StudentBrief(**it) for it in items]}


@router.get("/students/{student_id}/profile", response_model=ProfileOut, summary="学生画像查询")
def student_profile_view(student_id: int, db: Session = Depends(get_db),
                         current: User = Depends(require_teacher)):
    st = db.query(User).filter(User.id == student_id, User.role == "student").first()
    if not st:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生不存在")
    return student_profile(db, st)


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
    assignments: List[Assignment], db: Session
) -> List[TeacherAssignmentOut]:
    """批量组装教师作业列表，避免逐作业、逐题查询统计和配置。"""
    if not assignments:
        return []

    def id_chunks(ids: List[int], size: int = 500):
        for start in range(0, len(ids), size):
            yield ids[start:start + size]

    assignment_ids = [assignment.id for assignment in assignments]
    questions = []
    weights = {}
    for assignment_id_chunk in id_chunks(assignment_ids):
        for question, weight_pct in (
            db.query(Question, QuestionWeight.weight_pct)
            .outerjoin(
                QuestionWeight,
                QuestionWeight.question_id == Question.id,
            )
            .filter(Question.assignment_id.in_(assignment_id_chunk))
            .order_by(Question.assignment_id, Question.order_num, Question.id)
            .all()
        ):
            questions.append(question)
            if weight_pct is not None:
                weights[question.id] = float(weight_pct)
    questions.sort(key=lambda question: (
        question.assignment_id, question.order_num, question.id
    ))
    question_ids = [question.id for question in questions]
    question_counts = {}
    for question in questions:
        question_counts[question.assignment_id] = (
            question_counts.get(question.assignment_id, 0) + 1
        )

    submission_counts = {}
    for question_id_chunk in id_chunks(question_ids):
        count_rows = (
            db.query(
                Submission.question_id.label("question_id"),
                func.count(Submission.id).label("submission_count"),
            )
            .filter(Submission.question_id.in_(question_id_chunk))
            .group_by(Submission.question_id)
            .union_all(
                db.query(
                    Essay.question_id.label("question_id"),
                    func.count(Essay.id).label("submission_count"),
                )
                .filter(Essay.question_id.in_(question_id_chunk))
                .group_by(Essay.question_id)
            )
            .subquery()
        )
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
        ))
    return result


def _teacher_assignment_out(a: Assignment, db: Session) -> TeacherAssignmentOut:
    return _teacher_assignments_out([a], db)[0]


@router.post("/assignments", response_model=TeacherAssignmentOut, summary="发布作业")
def create_assignment(body: TeacherAssignmentCreate,
                      db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """创建一份作业并落库，学生端立即可见。
    standard_steps 无独立存储列：落库时并入 standard_answer（参考答案优先）。
    v0.5.0：mode=offline 时把 mode/workbook_id/page_range/deadline 写进 assignment_ext；
    workbook_id 必须指向本人上传的练习册。"""
    workbook = None
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
    )
    # v0.13.1：ext 行恒建（mode + deadline 两种模式都落，线上作业此前没 ext 行、
    # 截止时间会被静默丢弃）；练习册/页码仅线下有
    db.add(AssignmentExt(
        assignment_id=assignment.id,
        mode=body.mode,
        workbook_id=workbook.id if (body.mode == "offline" and workbook) else None,
        page_range=((body.page_range or "").strip() or None) if body.mode == "offline" else None,
        deadline=body.deadline,
    ))
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
    db.commit()
    db.refresh(assignment)
    return _teacher_assignment_out(assignment, db)


@router.get("/assignments", summary="已发布作业列表")
def list_teacher_assignments(db: Session = Depends(get_db),
                             current: User = Depends(require_teacher)):
    assignments = db.query(Assignment).order_by(Assignment.id).all()
    items = _teacher_assignments_out(assignments, db)
    return {"total": len(items), "items": items}


def _delete_unreferenced_submission_images(db: Session, file_paths: set[str]) -> None:
    """删除作业移除后不再被任何功能引用的提交原图。"""
    upload_dir = os.path.realpath(settings.UPLOAD_DIR)
    safe_paths = {}
    for stored_path in file_paths:
        absolute_path = os.path.realpath(
            stored_path if os.path.isabs(stored_path)
            else os.path.join(upload_dir, stored_path)
        )
        try:
            inside_upload_dir = os.path.commonpath(
                (upload_dir, absolute_path)
            ) == upload_dir
        except ValueError:
            inside_upload_dir = False
        if absolute_path == upload_dir or not inside_upload_dir:
            continue
        safe_paths[stored_path] = absolute_path

    if not safe_paths:
        return

    referenced_paths = set()
    reference_columns = (
        SubmissionImage.file_path,
        ChatSessionMessageImage.file_path,
        StudentQuestionCapture.image_path,
        Workbook.file_path,
    )
    paths = list(safe_paths)
    try:
        for start in range(0, len(paths), 500):
            path_chunk = paths[start:start + 500]
            for column in reference_columns:
                referenced_paths.update(
                    path
                    for (path,) in db.query(column).filter(
                        column.in_(path_chunk)
                    ).all()
                    if path
                )
    except Exception:
        db.rollback()
        logger.warning(
            "作业删除后批量检查提交图片引用失败，保留原图",
            exc_info=True,
        )
        return

    for stored_path, absolute_path in safe_paths.items():
        if stored_path in referenced_paths:
            continue
        try:
            os.remove(absolute_path)
        except FileNotFoundError:
            continue
        except Exception:
            # 作业删除已提交；清理失败只保留孤立文件，不应把成功删除显示成失败。
            db.rollback()
            logger.warning(
                "作业删除后清理提交图片失败（file_path=%s）",
                stored_path,
                exc_info=True,
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
    """删除教师作业管理列表中的一份作业（v0.3.0 新增）。教师端列表包含学生自主上传题，
    因此教师可删除任意列表可见的作业。事务内按外键依赖顺序级联删除：
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
    只统计/只提醒未全交的学生；全部完成的学生不会收到。仅限本人发布的作业。"""
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.created_by == current.id)
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    targets = students_not_fully_submitted(db, assignment)
    for st in targets:
        db.add(Notification(
            user_id=st.id,
            type="teacher_reminder",
            content=f"{current.name}提醒你：《{assignment.title}》还没有完成，记得及时提交哦",
            related_submission_id=None,
        ))
    db.commit()
    return {"reminded_count": len(targets)}


# ---------- 练习册知识库（v0.5.0 新增） ----------

_WORKBOOK_MAX_BYTES = 30 * 1024 * 1024
_WORKBOOK_SUBDIR = "workbooks"


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
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空，请重新上传")
    if len(data) > _WORKBOOK_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF 大小不能超过 30MB")
    target_dir = os.path.join(settings.UPLOAD_DIR, _WORKBOOK_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)
    stored_name = "{}_{}.pdf".format(
        datetime.now().strftime("%Y%m%d%H%M%S"), secrets.token_hex(4)
    )
    with open(os.path.join(target_dir, stored_name), "wb") as f:
        f.write(data)
    base = os.path.splitext(os.path.basename(filename))[0].strip()
    w = Workbook(
        teacher_id=current.id,
        title=base or "未命名练习册",
        file_path=f"{_WORKBOOK_SUBDIR}/{stored_name}",
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    # v0.6.0：上传成功后尝试把 PDF 第一页渲染成封面图（失败静默跳过，前端用书脊兜底）
    from ..services.covers import generate_cover

    generate_cover(w.id, os.path.join(settings.UPLOAD_DIR, w.file_path))
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
    db.query(AssignmentExt).filter(AssignmentExt.workbook_id == w.id) \
        .update({AssignmentExt.workbook_id: None}, synchronize_session=False)
    try:
        os.remove(os.path.join(settings.UPLOAD_DIR, w.file_path))
    except OSError:
        pass  # 文件已不在磁盘上时不阻塞删除元信息
    try:
        from ..services.covers import cover_file_path

        os.remove(cover_file_path(w.id))
    except OSError:
        pass  # 无封面图时忽略（v0.6.0 起顺带清封面文件）
    db.delete(w)
    db.commit()
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

    cs.ensure_migrated(db, current)
    return cs.list_sessions(db, current)


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

    cs.ensure_migrated(db, current)
    session = cs.get_own_session(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in cs.session_messages(db, session)
    ]


@router.delete("/agent/sessions/{session_id}", summary="删除一条教师对话会话（v0.6.0 新增）")
def teacher_agent_delete_session(session_id: int, db: Session = Depends(get_db),
                                 current: User = Depends(require_teacher)):
    """删除本人的一条会话及其全部消息；不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
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

    cs.ensure_migrated(db, current)
    if body.session_id is not None:
        session = cs.get_own_session(db, current, body.session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    else:
        session = cs.get_or_create_current(db, current)

    rows = cs.session_messages(db, session, limit=_AGENT_HISTORY_WINDOW)
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

    return StreamingResponse(
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

    cs.ensure_migrated(db, current)
    session = cs.current_session(db, current)
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
                          current: User = Depends(require_teacher)):
    """上传题目照片 → Provider 视觉转写 → 返回 {question_text, steps}（含图片回读信息）。
    规则与学生端 photo-transcribe 一致（jpg/png/webp、≤10MB、存同一 UPLOAD_DIR）；
    前端把 question_text 填入题干、steps 填入标准步骤，教师检查修改后再发布。
    注意：v1 直接复用学生作答转写能力（transcribe_image），未针对题目照片单独调 prompt。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = "{}_{}{}".format(
        datetime.now().strftime("%Y%m%d%H%M%S"),
        secrets.token_hex(4),
        _PHOTO_TYPES[file.content_type],
    )
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(data)
    result = get_provider().transcribe_image(data, file.content_type)
    return {
        "image_id": filename,
        "image_url": f"/api/uploads/{filename}",
        "question_text": result.get("question_text", ""),
        "steps": result.get("steps", []),
    }


@router.post("/photo-recognize-group", response_model=PhotoGroupTranscribeOut, summary="拍照识别大题")
async def photo_recognize_group(file: UploadFile = File(...),
                                current: User = Depends(require_teacher)):
    """上传大题照片 → Provider 视觉识别 → 返回 {stem, sub_questions}（v0.13.11）。

    识别入口在大题层级：一张图一次拆出共同题干与全部小题（照片里有解题过程
    才带每道小题的 steps），前端据此新建/填充一个大题，教师检查修改后再发布；
    不再逐个小题拍照识别。图片规则与单题识别一致（jpg/png/webp、≤10MB）。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = "{}_{}{}".format(
        datetime.now().strftime("%Y%m%d%H%M%S"),
        secrets.token_hex(4),
        _PHOTO_TYPES[file.content_type],
    )
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(data)
    result = get_provider().transcribe_group_image(data, file.content_type)
    return {
        "image_id": filename,
        "image_url": f"/api/uploads/{filename}",
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

    return build_teaching_suggestions(db)
