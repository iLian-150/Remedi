# /api/student/* 学生端
import json
import logging
import os
import re
import secrets
from datetime import datetime
from time import perf_counter
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session, aliased, joinedload, load_only
from starlette.concurrency import run_in_threadpool

from ..auth import require_student
from ..config import settings
from ..database import get_db
from ..models import (
    Assignment,
    AssignmentExt,
    AssignmentSetting,
    ChatMessage,
    Correction,
    Error,
    Essay,
    Notification,
    Question,
    QuestionGroup,
    QuestionGroupMember,
    StudentMistakeArchive,
    StudentMistakeCategoryReview,
    StudentMistakeEvent,
    StudentQuestionCapture,
    Step,
    Submission,
    SubmissionImage,
    SubmissionReview,
    User,
    Verification,
    Workbook,
)
from ..schemas import (
    AgentAssistantMessageIn,
    AgentChatIn,
    AgentHistoryItem,
    AssignmentScoreItem,
    ChatSessionOut,
    AssignmentDetail,
    BriefingOut,
    CorrectionCreate,
    CorrectionOut,
    DiagnosisOut,
    EssayBrief,
    EssayCreate,
    EssayOut,
    NotificationItem,
    NotificationListOut,
    NotificationUnreadCountOut,
    NotificationReadIn,
    NotificationReadOut,
    PhotoDiagnosisOut,
    PhotoReviewOut,
    PhotoCaptureSaveIn,
    PhotoTranscribeOut,
    ProfileOut,
    QuestionOut,
    RelatedMistakeOut,
    ReportScoresOut,
    SubjectReportOut,
    SubjectScoreItem,
    KnowledgePointErrorItem,
    MistakeArchiveIn,
    MistakeAssignmentArchiveIn,
    MistakeCategoryStudyIn,
    SubmissionBrief,
    SubmissionCreate,
    StudentMistakeOut,
    StudentMistakeCountOut,
    StudentQuestionCaptureCreate,
    VerificationCreate,
    VerificationOut,
    VerificationSubmitIn,
    VerificationSubmitOut,
)
from ..services import variant_gen
from ..services import deferral as deferral_svc
from ..services import reviews as review_svc
from ..services.streaming import ClosingStreamingResponse
from ..services.confidence import normalize_confidence
from ..services import scoring as scoring_svc
from ..services.diagnosis import (
    diagnose_submission,
    diagnose_visual_submission,
    present_diagnosis,
    present_error,
    verify_correction,
)
from ..services.answer_check import (
    student_visible_linear_error_detail,
    student_visible_reference_answer,
    student_visible_solution_steps,
)
from ..services.related_mistakes import (
    find_related_mistake,
    find_related_mistake_for_error,
    find_related_mistakes_for_questions,
)
from ..services.essays import present_essay, score_and_save_essay
from ..services.providers import get_provider
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_profile,
    student_report,
)

router = APIRouter(prefix="/api/student", tags=["student"])
logger = logging.getLogger(__name__)


def _student_accessible_question(db: Session, student: User, question_id: int) -> Question:
    """Load a public/teacher question or this student's own private question."""
    row = (
        db.query(Question, Assignment.created_by, User.role)
        .join(Assignment, Assignment.id == Question.assignment_id)
        .outerjoin(User, User.id == Assignment.created_by)
        .filter(Question.id == question_id)
        .first()
    )
    if row is None or (row[2] == "student" and row[1] != student.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
    return row[0]


# ---------- 学生诊断出参 ----------
# 低置信度诊断会同步进入教师审核队列，但错题和订正流程不等待审核；
# 学生立即看到诊断并可订正，成绩仍等教师审核后放出。

def present_for_student(
    submission: Submission,
    db: Session,
    *,
    steps: Optional[List[Step]] = None,
    errors: Optional[List[Error]] = None,
    review_status: Optional[str] = None,
) -> dict:
    """学生侧诊断出参：诊断立即可见；待审核时只暂缓下发成绩。"""
    out = present_diagnosis(submission, db, steps=steps, errors=errors)
    rstatus = (
        review_status
        if review_status is not None
        else review_svc.review_status(db, submission.id)
    )
    out["review_status"] = rstatus
    if rstatus == review_svc.PENDING:
        out["status"] = "pending_review"
        out["score"] = None
        return out
    # 评分系统：本题分与作业累计分共用进度计算中的批量成绩读取。
    vis = None
    if submission.question is not None:
        progress = scoring_svc.assignment_progress(
            db,
            submission.student_id,
            submission.question.assignment_id,
            current_submission=submission,
        )
        vis = progress.pop("current_score", None)
        if vis is not None:
            vis.update(progress)
    out["score"] = vis
    return out


# ---------- 作业 ----------

@router.get("/chat/context", summary="聊天选题器轻量上下文")
def student_chat_context(
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """只返回聊天选题器实际需要的作业标题、数学题与已提交题目 ID。"""
    visible_assignment = (
        Assignment.created_by.is_(None)
        | (~Assignment.created_by.in_(
            db.query(User.id).filter(User.role == "student")
        ))
    )
    has_submission = db.query(Submission.id).filter(
        Submission.question_id == Question.id,
        Submission.student_id == current.id,
    ).exists()
    rows = (
        db.query(
            Assignment.id,
            Assignment.title,
            Question.id,
            Question.stem,
            Question.order_num,
            has_submission.label("is_submitted"),
        )
        .outerjoin(
            Question,
            and_(
                Question.assignment_id == Assignment.id,
                Question.subject == "math",
            ),
        )
        .filter(visible_assignment)
        .order_by(Assignment.id, Question.order_num, Question.id)
        .all()
    )
    items_by_assignment = {}
    for assignment_id, title, question_id, stem, order_num, is_submitted in rows:
        item = items_by_assignment.setdefault(assignment_id, {
            "id": assignment_id,
            "title": title,
            "chat_questions": [],
            "submitted_chat_question_ids": [],
        })
        if question_id is None:
            continue
        item["chat_questions"].append({
            "id": question_id,
            "subject": "math",
            "stem": stem,
            "order_num": order_num,
        })
        if is_submitted:
            item["submitted_chat_question_ids"].append(question_id)
    items = list(items_by_assignment.values())
    return {"total": len(items), "items": items}


@router.get("/assignments", summary="作业列表")
def list_assignments(
    include_questions: bool = Query(default=False),
    include_submission_status: bool = Query(default=False),
    include_pending_count: bool = Query(default=False),
    include_chat_questions: bool = Query(default=False),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    visible_assignment = (
        Assignment.created_by.is_(None)
        | (~Assignment.created_by.in_(
            db.query(User.id).filter(User.role == "student")
        ))
    )
    assignment_query = (
        db.query(Assignment, AssignmentExt, AssignmentSetting, Workbook.title)
        .options(
            load_only(
                Assignment.id, Assignment.title, Assignment.description,
                Assignment.created_at,
            ),
            load_only(
                AssignmentExt.assignment_id, AssignmentExt.mode,
                AssignmentExt.workbook_id, AssignmentExt.page_range,
                AssignmentExt.deadline,
            ),
            load_only(
                AssignmentSetting.assignment_id,
                AssignmentSetting.allow_revision,
            ),
        )
        .outerjoin(AssignmentExt, AssignmentExt.assignment_id == Assignment.id)
        .outerjoin(AssignmentSetting, AssignmentSetting.assignment_id == Assignment.id)
        .outerjoin(Workbook, Workbook.id == AssignmentExt.workbook_id)
    )
    has_submission = db.query(Submission.id).filter(
        Submission.question_id == Question.id,
        Submission.student_id == current.id,
    ).exists()
    question_stats_query = db.query(
        Question.assignment_id.label("assignment_id"),
        func.count(Question.id).label("question_count"),
        func.sum(case((has_submission, 1), else_=0)).label(
            "submitted_count"
        ),
    )
    if not include_questions:
        question_stats_query = question_stats_query.add_columns(
            func.sum(case((Question.subject != "math", 1), else_=0)).label(
                "non_math_count"
            )
        )
    question_stats_subquery = (
        question_stats_query
        .join(Assignment, Assignment.id == Question.assignment_id)
        .filter(visible_assignment)
        .group_by(Question.assignment_id)
        .subquery()
    )
    assignment_query = assignment_query.outerjoin(
        question_stats_subquery,
        question_stats_subquery.c.assignment_id == Assignment.id,
    ).add_columns(
        question_stats_subquery.c.question_count,
        question_stats_subquery.c.submitted_count,
    )
    if not include_questions:
        assignment_query = assignment_query.add_columns(
            question_stats_subquery.c.non_math_count
        )

    latest_submissions = None
    if include_submission_status or include_pending_count:
        latest_submissions = (
            db.query(
                Question.assignment_id.label("assignment_id"),
                Submission.question_id.label("question_id"),
                SubmissionReview.status.label("review_status"),
                func.row_number().over(
                    partition_by=Submission.question_id,
                    order_by=(
                        Submission.submitted_at.desc(),
                        Submission.id.desc(),
                    ),
                ).label("row_num"),
            )
            .join(Question, Question.id == Submission.question_id)
            .join(Assignment, Assignment.id == Question.assignment_id)
            .outerjoin(
                SubmissionReview,
                SubmissionReview.submission_id == Submission.id,
            )
            .filter(Submission.student_id == current.id, visible_assignment)
            .subquery()
        )

    if include_submission_status:
        assignment_query = assignment_query.outerjoin(
            latest_submissions,
            and_(
                latest_submissions.c.assignment_id == Assignment.id,
                latest_submissions.c.row_num == 1,
            ),
        ).add_columns(
            latest_submissions.c.question_id,
            latest_submissions.c.review_status,
        )
    if include_pending_count:
        pending_counts = (
            db.query(
                latest_submissions.c.assignment_id.label("assignment_id"),
                func.count(latest_submissions.c.question_id).label("pending_count"),
            )
            .filter(
                latest_submissions.c.row_num == 1,
                latest_submissions.c.review_status == review_svc.PENDING,
            )
            .group_by(latest_submissions.c.assignment_id)
            .subquery()
        )
        assignment_query = assignment_query.outerjoin(
            pending_counts,
            pending_counts.c.assignment_id == Assignment.id,
        ).add_columns(pending_counts.c.pending_count)

    query_rows = (
        assignment_query
        .filter(visible_assignment)
        .order_by(Assignment.id)
        .all()
    )
    assignment_rows_by_id = {}
    question_stats = {}
    photo_required_assignment_ids = set()
    submitted_question_ids = {}
    pending_question_ids = {}
    pending_count_by_assignment = {}
    status_offset = 6 if include_questions else 7
    pending_count_offset = status_offset + (2 if include_submission_status else 0)
    for row in query_rows:
        assignment_id = row[0].id
        assignment_rows_by_id.setdefault(assignment_id, row[:4])
        question_count = int(row[4] or 0)
        submitted_count = int(row[5] or 0)
        question_stats[assignment_id] = (question_count, submitted_count)
        if not include_questions and int(row[6] or 0):
            photo_required_assignment_ids.add(assignment_id)
        if include_submission_status:
            question_id = row[status_offset]
            review_status = row[status_offset + 1]
            if question_id is not None:
                submitted_question_ids.setdefault(assignment_id, []).append(
                    question_id
                )
                if review_status == review_svc.PENDING:
                    pending_question_ids.setdefault(assignment_id, []).append(
                        question_id
                    )
        if include_pending_count:
            pending_count_by_assignment[assignment_id] = int(
                row[pending_count_offset] or 0
            )

    assignment_rows = list(assignment_rows_by_id.values())
    assignment_ids = list(assignment_rows_by_id)

    questions_by_assignment = {}
    groups_by_assignment = {}
    chat_questions_by_assignment = {}
    submitted_chat_question_ids = {}
    if (include_questions or include_chat_questions) and assignment_ids:
        question_rows = []
        for start in range(0, len(assignment_ids), 500):
            assignment_batch = assignment_ids[start:start + 500]
            if include_questions:
                question_query = db.query(
                    Question.id,
                    Question.assignment_id,
                    Question.subject,
                    Question.knowledge_point,
                    Question.stem,
                    Question.order_num,
                    QuestionGroupMember.group_id,
                )
                if include_chat_questions:
                    question_query = question_query.add_columns(
                        has_submission.label("is_submitted")
                    )
                question_rows.extend(
                    question_query
                    .outerjoin(
                        QuestionGroupMember,
                        QuestionGroupMember.question_id == Question.id,
                    )
                    .filter(Question.assignment_id.in_(assignment_batch))
                    .order_by(Question.assignment_id, Question.order_num, Question.id)
                    .all()
                )
            else:
                question_rows.extend(
                    db.query(
                        Question.id,
                        Question.assignment_id,
                        Question.stem,
                        Question.order_num,
                        has_submission.label("is_submitted"),
                    )
                    .filter(
                        Question.assignment_id.in_(assignment_batch),
                        Question.subject == "math",
                    )
                    .order_by(Question.assignment_id, Question.order_num, Question.id)
                    .all()
                )

        if include_questions:
            for start in range(0, len(assignment_ids), 500):
                for group_id, assignment_id, stem, order_num in db.query(
                    QuestionGroup.id,
                    QuestionGroup.assignment_id,
                    QuestionGroup.stem,
                    QuestionGroup.order_num,
                ).filter(
                    QuestionGroup.assignment_id.in_(assignment_ids[start:start + 500])
                ).order_by(QuestionGroup.assignment_id, QuestionGroup.order_num, QuestionGroup.id).all():
                    groups_by_assignment.setdefault(assignment_id, []).append({
                        "id": group_id,
                        "stem": stem,
                        "order_num": order_num,
                    })

            for row in question_rows:
                questions_by_assignment.setdefault(row.assignment_id, []).append({
                    "id": row.id,
                    "subject": row.subject,
                    "knowledge_point": row.knowledge_point,
                    "stem": row.stem,
                    "order_num": row.order_num,
                    "group_id": row.group_id,
                })
                if row.subject != "math":
                    photo_required_assignment_ids.add(row.assignment_id)
                if include_chat_questions and row.subject == "math":
                    chat_questions_by_assignment.setdefault(row.assignment_id, []).append({
                        "id": row.id,
                        "subject": "math",
                        "stem": row.stem,
                        "order_num": row.order_num,
                    })
                    if row.is_submitted:
                        submitted_chat_question_ids.setdefault(row.assignment_id, []).append(
                            row.id
                        )
        else:
            for row in question_rows:
                chat_questions_by_assignment.setdefault(row.assignment_id, []).append({
                    "id": row.id,
                    "subject": "math",
                    "stem": row.stem,
                    "order_num": row.order_num,
                })
                if row.is_submitted:
                    submitted_chat_question_ids.setdefault(row.assignment_id, []).append(
                        row.id
                    )

    result = []
    for assignment_row in assignment_rows:
        a, ext, setting, workbook_title = assignment_row[:4]
        question_count, submitted = question_stats.get(a.id, (0, 0))
        mode = (ext.mode or "online") if ext else "online"
        item = {
            "id": a.id, "title": a.title, "description": a.description,
            "question_count": question_count, "submitted_count": submitted,
            "created_at": a.created_at,
            # v0.5.0：发布模式与线下作业信息（mode/workbook_title/page_range/deadline）
            "mode": mode,
            "photo_required": mode == "offline" or a.id in photo_required_assignment_ids,
            "workbook_title": workbook_title if ext and ext.workbook_id else None,
            "page_range": ext.page_range if ext else None,
            "deadline": ext.deadline if ext else None,
            "allow_revision": bool(setting.allow_revision) if setting else False,
        }
        if include_questions:
            item["questions"] = questions_by_assignment.get(a.id, [])
            item["groups"] = groups_by_assignment.get(a.id, [])
        if include_chat_questions:
            item["chat_questions"] = chat_questions_by_assignment.get(a.id, [])
            item["submitted_chat_question_ids"] = submitted_chat_question_ids.get(a.id, [])
        if include_submission_status:
            item["submitted_question_ids"] = submitted_question_ids.get(a.id, [])
            item["pending_question_ids"] = pending_question_ids.get(a.id, [])
        if include_pending_count:
            item["pending_count"] = pending_count_by_assignment.get(a.id, 0)
        result.append(item)
    return {"total": len(result), "items": result}


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail, summary="作业详情")
def assignment_detail(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    assignment_rows = (
        db.query(
            Assignment,
            User.role,
            AssignmentExt,
            AssignmentSetting,
            Workbook.title,
            Question,
            QuestionGroupMember.group_id,
        )
        .outerjoin(User, User.id == Assignment.created_by)
        .outerjoin(AssignmentExt, AssignmentExt.assignment_id == Assignment.id)
        .outerjoin(AssignmentSetting, AssignmentSetting.assignment_id == Assignment.id)
        .outerjoin(Workbook, Workbook.id == AssignmentExt.workbook_id)
        .outerjoin(Question, Question.assignment_id == Assignment.id)
        .outerjoin(QuestionGroupMember, QuestionGroupMember.question_id == Question.id)
        .options(load_only(
            Assignment.id, Assignment.created_by, Assignment.title, Assignment.description,
        ), load_only(
            Question.id, Question.subject, Question.knowledge_point,
            Question.stem, Question.order_num,
        ))
        .filter(Assignment.id == assignment_id)
        .order_by(Question.order_num, Question.id)
        .all()
    )
    if not assignment_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    a, creator_role, ext, setting, workbook_title = assignment_rows[0][:5]
    if creator_role == "student":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    question_rows = [
        (row[5], row[6]) for row in assignment_rows if row[5] is not None
    ]
    # v0.13.1：大题分组（成员映射 + 大题列表）
    questions = [question for question, _ in question_rows]
    group_by_qid = {
        question.id: group_id for question, group_id in question_rows
    }
    groups = (
        db.query(QuestionGroup.id, QuestionGroup.stem, QuestionGroup.order_num)
        .filter(QuestionGroup.assignment_id == a.id)
        .order_by(QuestionGroup.order_num, QuestionGroup.id).all()
    )
    return AssignmentDetail(
        id=a.id, title=a.title, description=a.description,
        questions=[
            QuestionOut(
                id=q.id, subject=q.subject, knowledge_point=q.knowledge_point,
                stem=q.stem, order_num=q.order_num, group_id=group_by_qid.get(q.id),
            )
            for q in questions
        ],
        groups=[
            {"id": group_id, "stem": stem, "order_num": order_num}
            for group_id, stem, order_num in groups
        ],
        mode=(ext.mode or "online") if ext else "online",
        workbook_title=(
            workbook_title if ext and ext.workbook_id else None
        ),
        page_range=ext.page_range if ext else None,
        deadline=ext.deadline if ext else None,
        allow_revision=bool(setting.allow_revision) if setting else False,
    )


@router.get("/assignments/{assignment_id}/related-mistakes", summary="批量查看作业题目的历史同类错题")
def related_mistakes_for_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    assignment_rows = (
        db.query(Assignment.id, User.role, Question)
        .outerjoin(User, User.id == Assignment.created_by)
        .outerjoin(Question, Question.assignment_id == Assignment.id)
        .options(load_only(
            Question.id, Question.subject, Question.knowledge_point,
        ))
        .filter(Assignment.id == assignment_id)
        .all()
    )
    if not assignment_rows or assignment_rows[0][1] == "student":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")

    questions = [row[2] for row in assignment_rows if row[2] is not None]
    related_by_question = find_related_mistakes_for_questions(
        db,
        current.id,
        questions,
        exclude_assignment_id=assignment_rows[0][0],
    )
    return {
        str(question.id): related_by_question.get(question.id)
        for question in questions
    }


@router.get("/questions/{question_id}/related-mistake", response_model=Optional[RelatedMistakeOut],
            summary="查看题目对应的历史同类错题")
def related_mistake_for_question(question_id: int, db: Session = Depends(get_db),
                                 current: User = Depends(require_student)):
    question = _student_accessible_question(db, current, question_id)
    return find_related_mistake(
        db, current.id, question.subject, question.knowledge_point,
        exclude_assignment_id=question.assignment_id,
    )


# ---------- 数学诊断 ----------

@router.post("/submissions", response_model=DiagnosisOut, summary="提交数学作业并诊断")
def submit_math(data: SubmissionCreate, db: Session = Depends(get_db),
               current: User = Depends(require_student)):
    q = _student_accessible_question(db, current, data.question_id)
    if q.subject != "math":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该题是作文题，请使用 /api/student/essays 提交")
    # v0.13.1：按请求接收时刻检查提交锁，并固定本次是否进入延迟批改窗口。
    deferred_mode = deferral_svc.assert_can_submit(
        db, current, q, received_at=datetime.now()
    )
    if deferred_mode:
        return deferral_svc.deferred_out(deferral_svc.create_deferred(db, current, q, data.steps))
    submission, steps, errors = diagnose_submission(db, current, q, data.steps)
    # 本次作答正确率或错因置信度低于 60% 时进入教师审核队列。
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        review = review_svc.create_review_if_needed(db, submission)
    finally:
        db.expire_on_commit = expire_on_commit
    return present_for_student(
        submission, db, steps=steps, errors=errors,
        review_status=review.status if review is not None else review_svc.APPROVED,
    )


@router.get("/submissions", summary="我的提交记录")
def list_submissions(question_id: Optional[int] = Query(default=None),
                     limit: int = Query(default=20, le=100), offset: int = Query(default=0, ge=0),
                     db: Session = Depends(get_db), current: User = Depends(require_student)):
    query = db.query(Submission).filter(Submission.student_id == current.id)
    if question_id:
        query = query.filter(Submission.question_id == question_id)
    error_count_query = db.query(func.count(Error.id)).filter(
        Error.submission_id == Submission.id
    ).correlate(Submission).scalar_subquery()
    page_rows = query.outerjoin(
        SubmissionReview,
        SubmissionReview.submission_id == Submission.id,
    ).options(
        load_only(
            Submission.id, Submission.question_id,
            Submission.status, Submission.submitted_at,
        ),
        joinedload(Submission.question).load_only(
            Question.id, Question.assignment_id, Question.stem,
            Question.knowledge_point,
        ),
    ).add_columns(
        SubmissionReview.status.label("review_status"),
        error_count_query.label("error_count"),
        func.count(Submission.id).over().label("total")
    ).order_by(Submission.submitted_at.desc()).offset(offset).limit(limit).all()
    if page_rows:
        total = int(page_rows[0].total or 0)
        subs = []
        status_by_id = {}
        error_count_by_id = {}
        for submission, review_status, error_count, _ in page_rows:
            subs.append(submission)
            error_count_by_id[submission.id] = int(error_count or 0)
            if review_status is not None:
                status_by_id[submission.id] = review_status
    else:
        total = query.count()
        subs = []
        status_by_id = {}
        error_count_by_id = {}
    visible_subs = [
        s for s in subs
        if status_by_id.get(s.id, review_svc.APPROVED) != review_svc.PENDING
    ]
    scores_by_id = scoring_svc.visible_scores(db, visible_subs)
    items = []
    for s in subs:
        rstatus = status_by_id.get(s.id, review_svc.APPROVED)
        # 错题同步进入错题本和订正区；低置信度提交即使待审核也显示错误数。
        err_n = error_count_by_id.get(s.id, 0)
        # 评分系统：待审核不给分
        score = max_score = None
        if rstatus != review_svc.PENDING:
            vis = scores_by_id.get(s.id)
            if vis:
                score, max_score = vis["score"], vis["max_score"]
        question = s.question
        items.append(SubmissionBrief(
            id=s.id, question_id=s.question_id,
            question_stem=question.stem if question else "",
            knowledge_point=question.knowledge_point if question else "",
            status=s.status, error_count=err_n, submitted_at=s.submitted_at,
            review_status=rstatus,
            score=score, max_score=max_score,
        ))
    return {"total": total, "items": items}


@router.get("/submissions/{submission_id}", response_model=DiagnosisOut, summary="提交详情")
def submission_detail(submission_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    row = db.query(Submission, SubmissionReview.status).outerjoin(
        SubmissionReview,
        SubmissionReview.submission_id == Submission.id,
    ).options(
        joinedload(Submission.question).load_only(
            Question.id, Question.assignment_id, Question.subject, Question.stem,
        )
    ).filter(Submission.id == submission_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    s, review_status = row
    if s.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能查看自己的提交记录")
    return present_for_student(
        s, db,
        review_status=review_status or review_svc.APPROVED,
    )


def _mistake_category(subject: str, error_type: str, knowledge_point: str) -> tuple[str, str]:
    """Use the reference notebook's stable category rules, adapted to Remedi fields."""
    normalized_type = re.sub(r"\s+", "", error_type or "").casefold()
    normalized_knowledge = re.sub(r"\s+", "", knowledge_point or "").casefold()
    categories = (
        ("tense", "时态运用", ("时态", "tense")),
        ("agreement", "主谓一致", ("主谓一致", "主语和谓语一致", "subject-verb agreement")),
        ("article", "冠词使用", ("冠词", "article")),
        ("preposition", "介词使用", ("介词", "preposition")),
        ("word_form", "词形变化", ("词形", "单复数", "词性转换", "word form")),
        ("spelling", "拼写", ("拼写", "拼错", "spelling")),
        ("punctuation", "标点使用", ("标点", "punctuation")),
        ("capitalization", "大小写", ("大小写", "capitalization", "uppercase")),
        ("calculation", "计算与运算", ("计算", "运算", "算错", "calculation")),
        ("formula", "公式运用", ("公式", "formula")),
        ("concept", "概念理解", ("概念", "理解错误", "概念混淆")),
        ("unit", "单位换算", ("单位", "换算", "unit")),
        ("sign", "符号与正负号", ("符号", "正负号", "漏负号")),
        ("omission", "遗漏与漏写", ("遗漏", "漏写", "漏项", "漏答")),
        ("reading", "审题与信息提取", ("审题", "看错题", "读题", "信息提取")),
        ("expression", "表达与书写", ("表达", "书写", "格式")),
    )
    generic_types = {"语法错误", "知识错误", "知识性错误", "综合诊断", "待确认问题", "其他错误", "错误", "未分类"}
    primary = normalized_knowledge if normalized_type in generic_types else normalized_type
    subject_key = subject or "other"
    for code, label, tokens in categories:
        if any(token in primary for token in tokens) or any(token in normalized_knowledge for token in tokens):
            return f"{subject_key}:{code}", label
    fallback_source = knowledge_point if normalized_type in generic_types else error_type
    fallback = str(fallback_source or error_type or "待归类").strip()
    normalized_fallback = (re.sub(r"[\s，。；：、,.!?！？]+", "", fallback).casefold() or "待归类")[:160]
    return f"{subject_key}:other:{normalized_fallback}", fallback


def _record_mistake_event(db: Session, student_id: int, assignment_id: int,
                          event_type: str, payload: dict, created_at: datetime) -> None:
    db.add(StudentMistakeEvent(
        student_id=student_id,
        assignment_id=assignment_id,
        event_type=event_type,
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_at=created_at,
    ))


@router.get("/mistakes", response_model=List[StudentMistakeOut], summary="我的错题本")
def my_mistakes(
    archived: bool = Query(default=False),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """List this student's active or archived error occurrences without deleting diagnosis history."""
    archive_filter = None if include_archived else archived
    image_join_condition = SubmissionImage.submission_id == Submission.id
    if archive_filter is not None:
        archive_match = (
            StudentMistakeArchive.archived_at.isnot(None)
            if archive_filter
            else StudentMistakeArchive.archived_at.is_(None)
        )
        image_join_condition = and_(image_join_condition, archive_match)
    all_rows_query = (
        db.query(
            Error,
            Submission,
            Question,
            Assignment,
            Step,
            SubmissionReview.status.label("review_status"),
            StudentMistakeArchive.archived_at,
            SubmissionImage.file_path.label("image_path"),
        )
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .join(Assignment, Question.assignment_id == Assignment.id)
        .outerjoin(Step, Error.step_id == Step.id)
        .outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        )
        .outerjoin(
            StudentMistakeArchive,
            and_(
                StudentMistakeArchive.student_id == current.id,
                StudentMistakeArchive.error_id == Error.id,
            ),
        )
        .outerjoin(
            SubmissionImage,
            image_join_condition,
        )
        .options(
            load_only(
                Error.id, Error.knowledge_point, Error.error_type,
                Error.is_stubborn, Error.detail, Error.created_at,
            ),
            load_only(Submission.id, Submission.submitted_at),
            load_only(
                Question.id, Question.subject, Question.stem,
                Question.standard_answer, Question.order_num,
            ),
            load_only(Assignment.id, Assignment.title, Assignment.created_at),
            load_only(Step.id, Step.seq, Step.text),
        )
        .filter(Submission.student_id == current.id)
        .order_by(Error.created_at.desc(), Error.id.desc())
    )
    # 诊断错题立即进入错题本；待教师复核状态作为标记返回，不再过滤掉这批记录。
    archived_at_by_error = {}
    review_status_by_submission = {}
    image_path_by_submission = {}
    rows = []
    latest_by_category_assignment = {}
    for (
        error,
        submission,
        question,
        assignment,
        step,
        review_status,
        archived_at,
        image_path,
    ) in all_rows_query.yield_per(500):
        row = (error, submission, question, assignment, step)
        if (
            archive_filter is None
            or (archived_at is not None) == archive_filter
        ):
            rows.append(row)
        if review_status is not None:
            review_status_by_submission[submission.id] = review_status
        if image_path is not None:
            image_path_by_submission[submission.id] = image_path
        if archived_at is not None:
            archived_at_by_error[error.id] = archived_at
        # 查询按错题时间倒序；每个类别和作业只保存首次遇到的最新记录，
        # 后续生成相似错题只需要这些代表项，无需在内存保留全部历史 ORM 行。
        category_key, _ = _mistake_category(
            question.subject, error.error_type, error.knowledge_point
        )
        category_assignments = latest_by_category_assignment.setdefault(
            category_key, {}
        )
        category_assignments.setdefault(assignment.id, row)
    visible_assignment_ids = {assignment.id for _, _, _, assignment, _ in rows}
    visible_error_ids = [error.id for error, _, _, _, _ in rows]
    reviewed = set()
    visible_assignment_id_list = list(visible_assignment_ids)
    for start in range(0, len(visible_assignment_id_list), 500):
        assignment_id_chunk = visible_assignment_id_list[start:start + 500]
        reviewed.update(
            (assignment_id, category_key)
            for assignment_id, category_key in db.query(
                StudentMistakeCategoryReview.assignment_id,
                StudentMistakeCategoryReview.category_key,
            ).filter(
                StudentMistakeCategoryReview.student_id == current.id,
                StudentMistakeCategoryReview.assignment_id.in_(assignment_id_chunk),
            ).all()
        )
    correction_by_error = {}
    verification_by_error = {}
    for start in range(0, len(visible_error_ids), 500):
        error_id_chunk = visible_error_ids[start:start + 500]
        ranked_corrections = db.query(
            Correction.id.label("id"),
            Correction.error_id.label("error_id"),
            Correction.content.label("content"),
            Correction.is_correct.label("is_correct"),
            Correction.note.label("note"),
            Correction.submitted_at.label("submitted_at"),
            func.row_number().over(
                partition_by=Correction.error_id,
                order_by=(Correction.submitted_at.desc(), Correction.id.desc()),
            ).label("rank"),
        ).filter(
            Correction.student_id == current.id,
            Correction.error_id.in_(error_id_chunk),
        ).subquery()
        ranked_verifications = db.query(
            Verification.id.label("id"),
            Verification.source_error_id.label("source_error_id"),
            Verification.status.label("status"),
            func.row_number().over(
                partition_by=Verification.source_error_id,
                order_by=(Verification.created_at.desc(), Verification.id.desc()),
            ).label("rank"),
        ).filter(
            Verification.student_id == current.id,
            Verification.source_error_id.in_(error_id_chunk),
        ).subquery()
        latest_correction = ranked_corrections.c
        latest_verification = ranked_verifications.c
        latest_state_rows = db.query(
            Error.id.label("error_id"),
            latest_correction.id.label("correction_id"),
            latest_correction.content.label("correction_content"),
            latest_correction.is_correct.label("correction_is_correct"),
            latest_correction.note.label("correction_note"),
            latest_correction.submitted_at.label("correction_submitted_at"),
            latest_verification.status.label("verification_status"),
        ).select_from(Error).outerjoin(
            ranked_corrections,
            and_(
                latest_correction.error_id == Error.id,
                latest_correction.rank == 1,
            ),
        ).outerjoin(
            ranked_verifications,
            and_(
                latest_verification.source_error_id == Error.id,
                latest_verification.rank == 1,
            ),
        ).filter(Error.id.in_(error_id_chunk)).all()
        for row in latest_state_rows:
            if row.correction_id is not None:
                correction_by_error[row.error_id] = {
                    "id": row.correction_id,
                    "content": row.correction_content,
                    "is_correct": row.correction_is_correct,
                    "note": row.correction_note,
                    "submitted_at": row.correction_submitted_at,
                }
            if row.verification_status is not None:
                verification_by_error[row.error_id] = row.verification_status

    # 每个「类别 × 作业」只需保留最新一条错题。按作业时间扫描，并用堆按错题时间
    # 排序此前的作业；每条记录可直接取前 5 个相似错题，避免反复扫描全部历史记录。
    def datetime_order_key(value: datetime) -> int:
        return (
            ((value.toordinal() * 24 + value.hour) * 60 + value.minute) * 60
            + value.second
        ) * 1_000_000 + value.microsecond

    similar_by_category_assignment = {}
    for category_key, latest_by_assignment in latest_by_category_assignment.items():
        representatives = sorted(
            latest_by_assignment.values(),
            key=lambda entry: (entry[3].created_at, entry[3].id),
        )
        current_assignments = sorted(
            (entry[3] for entry in latest_by_assignment.values()),
            key=lambda assignment: (assignment.created_at, assignment.id),
        )
        top_five = []
        representative_index = 0
        for assignment in current_assignments:
            while (
                representative_index < len(representatives)
                and representatives[representative_index][3].created_at < assignment.created_at
            ):
                entry = representatives[representative_index]
                representative_index += 1
                error = entry[0]
                top_five.append(
                    (-datetime_order_key(error.created_at), -error.id, entry)
                )
                top_five.sort(key=lambda candidate: (candidate[0], candidate[1]))
                del top_five[5:]
            similar_by_category_assignment[(category_key, assignment.id)] = [
                {
                    "id": entry[0].id,
                    "submission_id": entry[1].id,
                    "assignment_id": entry[3].id,
                    "assignment_title": entry[3].title,
                    "assignment_created_at": entry[3].created_at,
                    "question_stem": entry[2].stem,
                }
                for _, _, entry in top_five
            ]

    result = []
    questions_by_id = {
        question.id: question
        for _, _, question, _, _ in rows
    }
    correct_answer_by_question = {}
    solution_steps_by_question = {}
    for question_id, question in questions_by_id.items():
        correct_answer = (
            student_visible_reference_answer(question.stem, question.standard_answer)
            if question.subject == "math" else question.standard_answer
        )
        correct_answer_by_question[question_id] = correct_answer
        solution_steps_by_question[question_id] = (
            student_visible_solution_steps(question.stem)
            if question.subject == "math" and correct_answer else []
        )
    linear_detail_by_step = {}
    for error, submission, question, assignment, step in rows:
        category_key, category_label = _mistake_category(
            question.subject, error.error_type, error.knowledge_point
        )
        correction = correction_by_error.get(error.id)
        correct_answer = correct_answer_by_question[question.id]
        step_key = (
            question.id,
            step.id if step else None,
            step.seq if step else None,
        )
        if step_key not in linear_detail_by_step:
            linear_detail_by_step[step_key] = student_visible_linear_error_detail(
                question.stem,
                step.text if step else None,
                step.seq if step else None,
            )
        result.append(StudentMistakeOut(
            id=error.id,
            submission_id=submission.id,
            review_status=review_status_by_submission.get(submission.id, review_svc.APPROVED),
            question_id=question.id,
            assignment_id=assignment.id,
            assignment_title=assignment.title,
            assignment_created_at=assignment.created_at,
            question_subject=question.subject,
            question_order=question.order_num,
            question_stem=question.stem,
            # This is this student's own review. Validate stored math answers, and
            # derive a complete answer for solvable one-variable equations.
            correct_answer=correct_answer,
            solution_steps=(
                solution_steps_by_question[question.id]
            ),
            knowledge_point=error.knowledge_point,
            error_type=error.error_type,
            is_stubborn=error.is_stubborn,
            detail=(
                linear_detail_by_step[step_key] or error.detail
            ),
            step_seq=step.seq if step else None,
            step_text=step.text if step else None,
            created_at=error.created_at,
            submitted_at=submission.submitted_at,
            category_key=category_key,
            category_label=category_label,
            category_studied=(assignment.id, category_key) in reviewed,
            archived_at=archived_at_by_error.get(error.id),
            similar_occurrences=similar_by_category_assignment.get(
                (category_key, assignment.id), []
            ),
            latest_correction=correction,
            verification_status=verification_by_error.get(error.id),
            image_url=(
                f"/api/uploads/{image_path_by_submission[submission.id]}"
                if submission.id in image_path_by_submission else None
            ),
        ))
    captures_query = db.query(StudentQuestionCapture).filter(
        StudentQuestionCapture.student_id == current.id,
        StudentQuestionCapture.saved_at.isnot(None),
    )
    if archive_filter is not None:
        archived_at_match = (
            StudentQuestionCapture.archived_at.isnot(None)
            if archive_filter
            else StudentQuestionCapture.archived_at.is_(None)
        )
        captures_query = captures_query.filter(archived_at_match)
    captures = captures_query.order_by(
        StudentQuestionCapture.created_at.desc(),
        StudentQuestionCapture.id.desc(),
    ).all()
    for capture in captures:
        result.append(StudentMistakeOut(
            id=-capture.id,
            submission_id=0,
            question_id=capture.question_id or 0,
            assignment_id=-capture.id,
            assignment_title="自主收录题目",
            assignment_created_at=capture.created_at,
            question_subject=capture.subject,
            question_order=1,
            question_stem=capture.question_text,
            knowledge_point="自主复习",
            error_type="主动收录",
            is_stubborn=False,
            detail=capture.explanation or "你主动加入错题本的题目，可以在这里继续复习。",
            step_seq=None,
            step_text=None,
            created_at=capture.saved_at or capture.created_at,
            submitted_at=capture.saved_at or capture.created_at,
            category_key=f"student_saved:{capture.id}",
            category_label="自主收录",
            category_studied=True,
            archived_at=capture.archived_at,
            similar_occurrences=[],
            latest_correction=None,
            verification_status=None,
            source_kind="student_saved",
            capture_id=capture.id,
            image_url=f"/api/uploads/{capture.image_path}" if capture.image_path else None,
        ))
    result.sort(key=lambda item: item.created_at, reverse=True)
    return result


@router.get("/mistakes/count", response_model=StudentMistakeCountOut,
            summary="我的诊断错题数量")
def my_mistake_count(subject: Optional[str] = Query(default=None),
                     db: Session = Depends(get_db),
                     current: User = Depends(require_student)):
    """Count diagnosis errors without assembling the full mistake notebook payload."""
    query = (
        db.query(func.count(Error.id))
        .select_from(Error)
        .join(Submission, Submission.id == Error.submission_id)
        .filter(Submission.student_id == current.id)
    )
    if subject:
        query = query.join(Question, Question.id == Submission.question_id) \
            .filter(Question.subject == subject)
    return {"count": int(query.scalar() or 0)}


@router.patch("/mistakes/categories", summary="标记错因类别学习状态")
def set_mistake_category_studied(body: MistakeCategoryStudyIn,
                                 db: Session = Depends(get_db),
                                 current: User = Depends(require_student)):
    category_rows = (
        db.query(
            Error.error_type,
            Error.knowledge_point,
            Question.subject,
            StudentMistakeCategoryReview,
        )
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .outerjoin(
            StudentMistakeArchive,
            and_(
                StudentMistakeArchive.error_id == Error.id,
                StudentMistakeArchive.student_id == current.id,
            ),
        )
        .outerjoin(
            StudentMistakeCategoryReview,
            and_(
                StudentMistakeCategoryReview.student_id == current.id,
                StudentMistakeCategoryReview.assignment_id == body.assignment_id,
                StudentMistakeCategoryReview.category_key == body.category_key,
            ),
        )
        .filter(
            Submission.student_id == current.id,
            Question.assignment_id == body.assignment_id,
            StudentMistakeArchive.error_id.is_(None),
        )
        .distinct()
        .all()
    )
    valid_keys = {
        _mistake_category(subject, error_type, knowledge_point)[0]
        for error_type, knowledge_point, subject, _ in category_rows
    }
    if body.category_key not in valid_keys:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业或错题类别不存在")

    state = next(
        (state for _, _, _, state in category_rows if state is not None),
        None,
    )
    if body.studied:
        if state:
            state.studied_at = datetime.now()
        else:
            db.add(StudentMistakeCategoryReview(
                student_id=current.id,
                assignment_id=body.assignment_id,
                category_key=body.category_key,
            ))
    elif state:
        db.delete(state)
    db.commit()
    return {"assignment_id": body.assignment_id, "category_key": body.category_key, "studied": body.studied}


@router.patch("/mistakes/{error_id}/archive", summary="移出或恢复单条错题")
def set_mistake_archived(error_id: int, body: MistakeArchiveIn,
                         db: Session = Depends(get_db),
                         current: User = Depends(require_student)):
    if error_id < 0:
        capture = db.query(StudentQuestionCapture).filter_by(
            id=-error_id, student_id=current.id
        ).first()
        if not capture or capture.saved_at is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到这条错题记录")
        capture.archived_at = datetime.now() if body.archived else None
        db.commit()
        return {"id": error_id, "student_id": current.id, "archived_at": capture.archived_at}

    target = (
        db.query(Error.id, Question.assignment_id)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(Error.id == error_id, Submission.student_id == current.id)
        .first()
    )
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到这条错题记录")
    _, assignment_id = target
    state = db.query(StudentMistakeArchive).filter_by(
        student_id=current.id, error_id=error_id
    ).first()
    if bool(state) == body.archived:
        return {"id": error_id, "student_id": current.id, "archived_at": state.archived_at if state else None}

    now = datetime.now()
    if body.archived:
        state = StudentMistakeArchive(student_id=current.id, error_id=error_id, archived_at=now)
        db.add(state)
        event_type = "mistake_archived"
        payload = {"occurrence_id": error_id, "student_id": current.id}
    else:
        db.delete(state)
        event_type = "mistake_restored"
        payload = {"occurrence_id": error_id, "student_id": current.id}
    _record_mistake_event(db, current.id, assignment_id, event_type, payload, now)
    db.commit()
    return {"id": error_id, "student_id": current.id, "archived_at": now if body.archived else None}


@router.patch("/mistakes/assignments/{assignment_id}/archive", summary="移出或恢复一份作业的错题")
def set_mistake_assignment_archived(assignment_id: int, body: MistakeAssignmentArchiveIn,
                                    db: Session = Depends(get_db),
                                    current: User = Depends(require_student)):
    if assignment_id < 0:
        capture = db.query(StudentQuestionCapture).filter_by(
            id=-assignment_id, student_id=current.id
        ).first()
        if not capture or capture.saved_at is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到这份错题记录")
        capture.archived_at = datetime.now() if body.archived else None
        db.commit()
        return {"assignment_id": assignment_id, "archived_ids": [assignment_id],
                "archived_at": capture.archived_at}

    rows_query = (
        db.query(Error.id, Error.error_type, Error.knowledge_point, Question.subject)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(Submission.student_id == current.id, Question.assignment_id == assignment_id)
    )
    if body.archived:
        rows_query = rows_query.outerjoin(
            StudentMistakeArchive,
            and_(
                StudentMistakeArchive.error_id == Error.id,
                StudentMistakeArchive.student_id == current.id,
            ),
        ).add_columns(
            StudentMistakeArchive.error_id.label("archived_error_id")
        )
    rows = rows_query.all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业没有可整理的错题")

    if body.archived:
        active_rows = [
            (error_id, error_type, knowledge_point, subject)
            for error_id, error_type, knowledge_point, subject, archived_error_id in rows
            if archived_error_id is None
        ]
        if not active_rows:
            return {"assignment_id": assignment_id, "archived_ids": []}
        categories = {
            _mistake_category(subject, error_type, knowledge_point)[0]
            for _, error_type, knowledge_point, subject in active_rows
        }
        reviewed = {
            item.category_key for item in db.query(StudentMistakeCategoryReview)
            .filter_by(student_id=current.id, assignment_id=assignment_id).all()
        }
        remaining = categories - reviewed
        if remaining:
            raise HTTPException(status.HTTP_409_CONFLICT, f"还有 {len(remaining)} 类错误没有标记为已学习。")
        now = datetime.now()
        archived_ids = [error_id for error_id, _, _, _ in active_rows]
        db.add_all(StudentMistakeArchive(student_id=current.id, error_id=error_id, archived_at=now)
                    for error_id in archived_ids)
        _record_mistake_event(db, current.id, assignment_id, "mistake_assignment_archived",
                              {"student_id": current.id, "occurrence_ids": archived_ids}, now)
        db.commit()
        return {"assignment_id": assignment_id, "archived_ids": archived_ids, "archived_at": now}

    occurrence_ids = list(dict.fromkeys(body.occurrence_ids))
    if not occurrence_ids:
        return {"assignment_id": assignment_id, "archived_ids": []}
    restore_states = []
    for start in range(0, len(occurrence_ids), 500):
        restore_states.extend(
            db.query(StudentMistakeArchive)
            .join(Error, StudentMistakeArchive.error_id == Error.id)
            .join(Submission, Error.submission_id == Submission.id)
            .join(Question, Submission.question_id == Question.id)
            .filter(
                StudentMistakeArchive.student_id == current.id,
                StudentMistakeArchive.error_id.in_(occurrence_ids[start:start + 500]),
                Submission.student_id == current.id,
                Question.assignment_id == assignment_id,
            ).all()
        )
    restored_ids = [state.error_id for state in restore_states]
    if restored_ids:
        for state in restore_states:
            db.delete(state)
        now = datetime.now()
        _record_mistake_event(db, current.id, assignment_id, "mistake_assignment_restored",
                              {"student_id": current.id, "occurrence_ids": restored_ids}, now)
        db.commit()
    return {"assignment_id": assignment_id, "archived_ids": restored_ids}


# ---------- 作文 ----------

@router.post("/essays", response_model=EssayOut, summary="提交英语作文并评分")
def submit_essay(body: EssayCreate, db: Session = Depends(get_db),
                 current: User = Depends(require_student)):
    question = None
    if body.question_id:
        question = _student_accessible_question(db, current, body.question_id)
        if question.subject != "english":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该题不是作文题")
    return score_and_save_essay(db, current, body.text.strip(), question)


@router.get("/essays", summary="我的作文列表")
def list_essays(limit: int = Query(default=20, le=100), offset: int = Query(default=0, ge=0),
                db: Session = Depends(get_db), current: User = Depends(require_student)):
    import json
    query = db.query(Essay).options(load_only(
        Essay.id,
        Essay.question_id,
        Essay.scores_json,
        Essay.submitted_at,
    )).filter(Essay.student_id == current.id)
    page_rows = query.add_columns(
        func.count(Essay.id).over().label("total")
    ).order_by(Essay.submitted_at.desc()).offset(offset).limit(limit).all()
    if page_rows:
        total = int(page_rows[0].total or 0)
        essays = [essay for essay, _ in page_rows]
    else:
        total = query.count()
        essays = []
    items = [EssayBrief(
        essay_id=e.id, question_id=e.question_id,
        total=json.loads(e.scores_json).get("total", 0),
        submitted_at=e.submitted_at,
    ) for e in essays]
    return {"total": total, "items": items}


@router.get("/essays/{essay_id}", response_model=EssayOut, summary="作文详情")
def essay_detail(essay_id: int, db: Session = Depends(get_db),
                 current: User = Depends(require_student)):
    e = db.query(Essay).filter(Essay.id == essay_id).first()
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作文不存在")
    if e.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能查看自己的作文")
    return present_essay(e, with_text=True)


# ---------- 订正 ----------

@router.post("/corrections", response_model=CorrectionOut, summary="提交订正")
def submit_correction(body: CorrectionCreate, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    err = (
        db.query(Error)
        .options(
            load_only(
                Error.id, Error.submission_id, Error.step_id,
                Error.knowledge_point,
            ),
            joinedload(Error.submission)
            .load_only(
                Submission.id, Submission.student_id, Submission.question_id,
            )
            .joinedload(Submission.question)
            .load_only(Question.id, Question.subject),
            joinedload(Error.step).load_only(
                Step.id, Step.submission_id, Step.seq, Step.text,
            ),
        )
        .filter(Error.id == body.error_id)
        .first()
    )
    if not err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    sub = err.submission
    if not sub or sub.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能订正自己的错误")
    knowledge_point = err.knowledge_point
    is_correct, note = verify_correction(db, err, body.content.strip())
    c = Correction(error_id=err.id, student_id=current.id,
                   content=body.content.strip(), is_correct=is_correct, note=note)
    db.add(c)
    db.flush()
    out = CorrectionOut.model_validate(c)
    # v0.4.0：订正成功 → 提示可去做二次验证（通过验证才算知识点已修复）
    out.can_verify = is_correct is True
    out.knowledge_point = knowledge_point
    db.commit()
    return out


# ---------- 二次验证（v0.4.0 新增）：订正后做变式题，通过才算知识点已修复 ----------

def _verification_out(v: Verification) -> dict:
    """出参组装：只下发题干，variant_json 里的答案/标准步骤不外泄。"""
    try:
        variant = json.loads(v.variant_json)
    except Exception:
        variant = {}
    return {
        "id": v.id,
        "knowledge_point": v.knowledge_point,
        "prompt": variant.get("prompt", ""),
        "status": v.status,
        "attempts": v.attempts,
        "source_error_id": v.source_error_id,
        "created_at": v.created_at,
        "completed_at": v.completed_at,
    }


@router.post("/verifications", response_model=VerificationOut, summary="创建二次验证（变式题）")
def create_verification(body: VerificationCreate, db: Session = Depends(get_db),
                        current: User = Depends(require_student)):
    """为某知识点创建一道变式题；已有未完成的（pending）直接复用，不重复出题。
    已 failed 的不复用——重新 POST 即生成新题重试。"""
    kp = body.knowledge_point.strip()
    existing = (
        db.query(Verification)
        .filter(Verification.student_id == current.id,
                Verification.knowledge_point == kp,
                Verification.status == "pending")
        .order_by(Verification.created_at.desc(), Verification.id.desc())
        .first()
    )
    if existing:
        return _verification_out(existing)

    source_error_id = body.source_error_id
    if source_error_id is not None:
        own_error = (
            db.query(Error.id)
            .join(Submission, Submission.id == Error.submission_id)
            .filter(
                Error.id == source_error_id,
                Submission.student_id == current.id,
            )
            .first()
        )
        if own_error is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_error_id 不是你的错题记录")
    else:
        latest_query = (
            db.query(Error.id)
            .join(Submission, Error.submission_id == Submission.id)
            .filter(Submission.student_id == current.id, Error.knowledge_point == kp)
        )
        latest = latest_query.order_by(Error.created_at.desc(), Error.id.desc()).first()
        source_error_id = latest[0] if latest else None

    variant = variant_gen.generate_variant(kp)
    v = Verification(
        student_id=current.id,
        knowledge_point=kp,
        source_error_id=source_error_id,
        variant_json=json.dumps(variant, ensure_ascii=False),
        status="pending",
        attempts=0,
    )
    db.add(v)
    db.flush()
    out = _verification_out(v)
    db.commit()
    return out


@router.get("/verifications", response_model=List[VerificationOut], summary="我的验证列表")
def list_verifications(db: Session = Depends(get_db), current: User = Depends(require_student)):
    rows = (
        db.query(Verification)
        .filter(Verification.student_id == current.id)
        .order_by(Verification.created_at.desc(), Verification.id.desc())
        .limit(50)
        .all()
    )
    return [_verification_out(v) for v in rows]


@router.post("/verifications/{verification_id}/submit", response_model=VerificationSubmitOut,
             summary="提交验证作答并判定")
def submit_verification(verification_id: int, body: VerificationSubmitIn,
                        db: Session = Depends(get_db), current: User = Depends(require_student)):
    """用 variant_gen.judge_steps 按步骤等价判定：全对 → passed 并落 completed_at；
    有错 → failed、attempts+1，返回首个出错步与解析，可对同一条继续提交（重做本题）
    或重新 POST /verifications 换一道新题。"""
    v = db.query(Verification).filter(Verification.id == verification_id).first()
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "验证记录不存在")
    if v.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能提交自己的验证")
    if v.status == "passed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "这道验证已经通过啦，去学习报告里再开一道新的吧")
    try:
        variant = json.loads(v.variant_json)
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "验证题目数据损坏，请重新创建")
    result = variant_gen.judge_steps(variant, body.steps)
    v.attempts += 1
    if result["passed"]:
        v.status = "passed"
        v.completed_at = datetime.now()
    else:
        v.status = "failed"
    out = {
        "id": v.id,
        "knowledge_point": v.knowledge_point,
        "status": v.status,
        "attempts": v.attempts,
        "passed": result["passed"],
        "first_error_seq": result["first_error_seq"],
        "error_type": result["error_type"],
        "detail": result["detail"],
        "steps": result["steps"],
    }
    db.commit()
    return out


# ---------- 画像 ----------

@router.get("/profile", response_model=ProfileOut, summary="我的学习画像")
def my_profile(db: Session = Depends(get_db), current: User = Depends(require_student)):
    # v0.9.0：学生自查口径——待审核提交不计入画像（教师查学生画像仍全量）
    return student_profile(db, current, visible_only=True)


# ---------- 首页简报 / 拍照转写（v0.2.0 新增） ----------

@router.get("/briefing", response_model=BriefingOut, summary="首页待办简报")
def briefing(db: Session = Depends(get_db), current: User = Depends(require_student)):
    return student_briefing(db, current, visible_only=True)


# ---------- 学习报告（v0.2.1 新增）：科目 → 知识点 → 错题时间线 → 步骤诊断 ----------

@router.get("/report", response_model=List[SubjectReportOut], summary="我的学习报告（按科目）")
def my_report(db: Session = Depends(get_db), current: User = Depends(require_student)):
    return student_report(db, current, visible_only=True)


@router.get("/report/scores", response_model=ReportScoresOut, summary="我的成绩分析（评分系统新增）")
def my_report_scores(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """成绩分析：历次作业得分序列 + 学科/总体平均得分率。
    只统计审核已通过且有分的提交（分数跟诊断一起过审，待审核不计入）。"""
    data = scoring_svc.student_score_report(db, current)
    return ReportScoresOut(
        items=[AssignmentScoreItem(**it) for it in data["items"]],
        subjects=[SubjectScoreItem(**s) for s in data["subjects"]],
        overall_avg_rate=data["overall_avg_rate"],
    )


@router.get(
    "/report/knowledge-points/{kp_name}/errors",
    response_model=List[KnowledgePointErrorItem],
    summary="知识点错题时间线",
)
def my_knowledge_point_errors(kp_name: str, db: Session = Depends(get_db),
                              current: User = Depends(require_student)):
    return knowledge_point_errors(db, current, kp_name, visible_only=True)


_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp"}
_PHOTO_MAX_BYTES = 10 * 1024 * 1024


def _write_uploaded_file(path: str, data: bytes) -> None:
    with open(path, "wb") as image_file:
        image_file.write(data)


def _add_submission_image_link(db: Session, submission: Submission,
                               file_path: str, file_name: str) -> None:
    """暂存图片关联，由调用方与审核记录一起提交。"""
    db.add(SubmissionImage(
        submission_id=submission.id,
        file_path=file_path,
        file_name=file_name[:255],
    ))


def _has_recognized_student_work(recognition: dict, step_texts: List[str]) -> bool:
    """模型返回了作答步骤时，以步骤内容作为有作答的可靠证据。

    视觉模型偶尔会同时给出非空 steps 和 student_work_detected=false；
    不能让矛盾的标记把已识别出的学生作答误分流成纯题目问答。
    """
    if any(text.strip() for text in step_texts):
        return True
    return recognition.get("student_work_detected") is True


def _visual_review_confidence(confidence: float, recognition: dict) -> float:
    """needs_image_review 本身就是低置信信号，确保这次作答进入教师复核。"""
    return min(confidence, 0.59) if recognition.get("needs_image_review") else confidence


def _visual_question_context(question: Question) -> str:
    """向视觉模型提供学科、题目和教师参考内容，直接按图片证据诊断。"""
    return (
        f"学科：{question.subject}\n题目：{question.stem}\n"
        f"教师参考答案或步骤：{question.standard_answer or '未提供'}"
    )


@router.post("/photo-review", response_model=PhotoReviewOut, summary="识别题目图片并按作答情况分流")
async def photo_review(
    file: UploadFile = File(...),
    model_file: Optional[UploadFile] = File(default=None),
    question_id: Optional[int] = Form(default=None),
    question_context: str = Form(default=""),
    save_to_chat: bool = Form(default=False),
    chat_session_id: Optional[int] = Form(default=None),
    chat_prompt: str = Form(default=""),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """没有学生作答时只进入问答，并暂存图片供学生之后主动收录；有作答时复用视觉诊断。"""
    request_started_at = perf_counter()
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read(_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    model_data = data
    model_content_type = file.content_type or "image/jpeg"
    if model_file is not None:
        if model_file.content_type not in _PHOTO_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "模型处理图片格式无效")
        model_data = await model_file.read(_PHOTO_MAX_BYTES + 1)
        if not model_data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "模型处理图片为空，请重新上传")
        if len(model_data) > _PHOTO_MAX_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "模型处理图片大小不能超过 10MB")
        model_content_type = model_file.content_type or "image/jpeg"
    received_at = datetime.now()

    question = None
    if question_id is not None:
        question = _student_accessible_question(db, current, question_id)
    context = (
        _visual_question_context(question)
        if question else question_context
    )

    chat_session = None
    stored_image_path = None
    image_url = None
    if save_to_chat:
        from ..services import chat_sessions as cs

        if chat_session_id is not None:
            chat_session = cs.get_own_session_or_migrate(
                db, current, chat_session_id
            )
            if chat_session is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
        else:
            chat_session = cs.get_or_create_current(db, current)
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        filename = "{}_{}{}".format(
            datetime.now().strftime("%Y%m%d%H%M%S"),
            secrets.token_hex(8),
            _PHOTO_TYPES[file.content_type],
        )
        stored_image_path = filename
        image_url = f"/api/uploads/{filename}"
        await run_in_threadpool(
            _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, filename), data
        )
        chat_user_text = "上传了一张作业照片。"
        if chat_prompt.strip():
            chat_user_text += f"\n补充说明：{chat_prompt.strip()[:2000]}"
        chat_user_message = cs.append_message(db, chat_session, "user", chat_user_text)
        cs.attach_image(
            db,
            chat_user_message,
            stored_image_path,
            os.path.basename((file.filename or "").replace("\\", "/")) or "作业照片",
        )

    # 诊断错误由聊天页和并行的视觉讲解流共同呈现；这里不写助手占位消息，
    # 避免视觉讲解成功后历史会话仍残留一条误导性的“识别失败”回复。
    vision_started_at = perf_counter()
    try:
        recognition = await run_in_threadpool(
            get_provider().diagnose_homework_image, model_data, model_content_type, context
        )
    except Exception as exc:
        logger.exception("学生图片诊断模型调用失败（student_id=%s）", current.id)
        if stored_image_path:
            failure_message = "图片识别服务暂时不可用，照片已保存在当前对话中，请稍后重新识别。"
        else:
            failure_message = "图片识别服务暂时不可用，请稍后重新上传。"
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            failure_message,
        ) from exc
    vision_elapsed = perf_counter() - vision_started_at
    logger.info(
        "照片视觉识别完成（耗时 %.2f 秒，原图 %d 字节，模型输入 %d 字节）",
        vision_elapsed, len(data), len(model_data),
    )
    confidence = normalize_confidence(recognition.get("confidence", 0.0))
    recognized_subject = question.subject if question else str(
        recognition.get("subject", "other") or "other"
    )
    visual_steps = recognition.get("steps", [])
    steps = [str(step.get("text", "")).strip() for step in visual_steps
             if isinstance(step, dict) and str(step.get("text", "")).strip()]
    has_work = _has_recognized_student_work(recognition, steps)

    question_text = str(recognition.get("question_text", "")).strip() or (question.stem if question else "")
    recognized_knowledge_point = str(recognition.get("knowledge_point", "")).strip()[:64]
    if not has_work:
        if recognition.get("needs_image_review") or confidence < 0.45:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "照片暂时无法可靠辨认，没有生成错题记录。请拍清楚后重试。",
            )
        if not question_text:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "没有识别到题目内容，请拍清楚题干后重试。",
            )
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        filename = stored_image_path
        if filename is None:
            filename = "{}_{}{}".format(
                datetime.now().strftime("%Y%m%d%H%M%S"),
                secrets.token_hex(8),
                _PHOTO_TYPES[file.content_type],
            )
            await run_in_threadpool(
                _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, filename), data
            )
            image_url = f"/api/uploads/{filename}"
        capture = StudentQuestionCapture(
            student_id=current.id,
            question_id=question.id if question else None,
            subject=recognized_subject,
            question_text=question_text,
            image_path=filename,
        )
        db.add(capture)
        expire_on_commit = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.commit()
        finally:
            db.expire_on_commit = expire_on_commit
        related_mistake = find_related_mistake(
            db, current.id, recognized_subject,
            question.knowledge_point if question else recognized_knowledge_point,
            exclude_assignment_id=question.assignment_id if question else None,
        )
        # 当前问答已由独立的视觉流式接口直接基于原图生成；这里只保存用户图片，
        # 避免先写入「识别到题目」占位助手消息，再重复保存最终讲解。
        session_id = chat_session.id if chat_session is not None else None
        logger.info(
            "照片处理阶段完成（mode=answer，视觉识别 %.2f 秒，接口总耗时 %.2f 秒）",
            vision_elapsed, perf_counter() - request_started_at,
        )
        return {"mode": "answer", "question_text": question_text, "steps": [],
                "capture_id": capture.id, "diagnosis": None, "session_id": session_id,
                "image_url": image_url, "related_mistake": related_mistake}

    if not steps:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "照片里似乎有作答，但步骤无法辨认。请重拍，或手动整理步骤后再提交。",
        )
    if question is None:
        if not question_text:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "题目内容没有识别清楚，暂时无法核对作答。请重拍，或在聊天里补充题干。",
            )
        # 自由上传且检测到作答时，为这次诊断建立仅归属学生自己的作业容器，
        # 保持现有 Submission → Step → Error 错题链路不变。学生作业列表会隐藏该容器。
        assignment = Assignment(
            title=f"自主上传题目 · {datetime.now():%Y-%m-%d %H:%M}",
            description="由学生在学习助手上传并自动诊断的题目。",
            created_by=current.id,
        )
        db.add(assignment)
        db.flush()
        question = Question(
            assignment_id=assignment.id,
            subject=recognized_subject,
            knowledge_point=recognized_knowledge_point or "自主上传题",
            stem=question_text,
            order_num=1,
        )
        db.add(question)
        db.flush()

    # 只有视觉模型确认图片里有作答后才应用提交锁；题目照片仍可用于自由提问。
    # 截止前收下的作业先保存原图与识别步骤，截止后由统一批改任务重新诊断原图。
    deferred_mode = deferral_svc.assert_can_submit(
        db, current, question, received_at=received_at
    )
    if deferred_mode:
        if stored_image_path is None:
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
            stored_image_path = "{}_{}{}".format(
                datetime.now().strftime("%Y%m%d%H%M%S"),
                secrets.token_hex(8),
                _PHOTO_TYPES[file.content_type],
            )
            await run_in_threadpool(
                _write_uploaded_file,
                os.path.join(settings.UPLOAD_DIR, stored_image_path), data,
            )
        image_name = os.path.basename((file.filename or "").replace("\\", "/")) or "作业照片"
        submission = deferral_svc.create_deferred(
            db, current, question, steps,
            image_path=stored_image_path, image_name=image_name,
        )
        related_mistake = find_related_mistake(
            db, current.id, question.subject, question.knowledge_point,
            exclude_assignment_id=question.assignment_id,
        )
        session_id = chat_session.id if chat_session is not None else None
        return {
            "mode": "diagnosis",
            "question_text": question_text,
            "steps": steps,
            "capture_id": None,
            "diagnosis": deferral_svc.deferred_out(submission),
            "session_id": session_id,
            "image_url": f"/api/uploads/{stored_image_path}",
            "related_mistake": related_mistake,
        }

    submission, diagnosed_steps, diagnosed_errors = diagnose_visual_submission(
        db, current, question, visual_steps
    )
    if stored_image_path is None:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        stored_image_path = "{}_{}{}".format(
            datetime.now().strftime("%Y%m%d%H%M%S"),
            secrets.token_hex(8),
            _PHOTO_TYPES[file.content_type],
        )
        await run_in_threadpool(
            _write_uploaded_file,
            os.path.join(settings.UPLOAD_DIR, stored_image_path), data,
        )
    _add_submission_image_link(
        db,
        submission,
        stored_image_path,
        os.path.basename((file.filename or "").replace("\\", "/")) or "作业照片",
    )
    review = review_svc.create_review_if_needed(
        db, submission,
        confidence_signals=review_svc.visual_confidence_signals(
            _visual_review_confidence(confidence, recognition), visual_steps
        ),
        commit=False,
    )
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    related_mistake = find_related_mistake(
        db, current.id, question.subject, question.knowledge_point,
        exclude_assignment_id=question.assignment_id,
    )
    diagnosis = present_for_student(
        submission, db, steps=diagnosed_steps, errors=diagnosed_errors,
        review_status=review.status if review is not None else review_svc.APPROVED,
    )
    # 学习助手随后会基于识别出的题目和步骤流式回答，避免在对话历史里
    # 先保存一条“等待审核”的占位回复，再额外显示批改结果卡片。
    session_id = chat_session.id if chat_session is not None else None
    logger.info(
        "照片处理阶段完成（mode=diagnosis，视觉识别 %.2f 秒，接口总耗时 %.2f 秒）",
        vision_elapsed, perf_counter() - request_started_at,
    )
    return {"mode": "diagnosis", "question_text": question_text,
            "steps": steps, "capture_id": None, "diagnosis": diagnosis,
            "session_id": session_id,
            "image_url": f"/api/uploads/{stored_image_path}",
            "related_mistake": related_mistake}


@router.post("/photo-captures/{capture_id}/save", summary="将自主上传题目加入错题本")
def save_photo_capture(capture_id: int, body: PhotoCaptureSaveIn,
                       db: Session = Depends(get_db),
                       current: User = Depends(require_student)):
    capture = db.query(StudentQuestionCapture).filter_by(
        id=capture_id, student_id=current.id
    ).first()
    if not capture:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到这道暂存题目")
    if capture.saved_at is None:
        capture.saved_at = datetime.now()
    if body.explanation.strip():
        capture.explanation = body.explanation.strip()
    capture.archived_at = None
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    return {"capture_id": capture.id, "saved": True, "saved_at": capture.saved_at}


@router.post("/question-captures", summary="将文本题目加入错题本")
def save_text_question(body: StudentQuestionCaptureCreate,
                       db: Session = Depends(get_db),
                       current: User = Depends(require_student)):
    question_text = body.question_text.strip()
    if not question_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "题目内容不能为空")
    saved_at = datetime.now()
    capture = StudentQuestionCapture(
        student_id=current.id,
        subject=body.subject.strip() or "math",
        question_text=question_text,
        image_path="",
        explanation=body.explanation.strip() or None,
        saved_at=saved_at,
    )
    db.add(capture)
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    return {"capture_id": capture.id, "saved": True, "saved_at": saved_at}


@router.post("/photo-transcribe", response_model=PhotoTranscribeOut, summary="拍照转写作业")
async def photo_transcribe(file: UploadFile = File(...),
                           current: User = Depends(require_student)):
    """上传作业照片 → Provider 视觉转写 → 返回 {image_id, image_url, question_text, steps}。
    图片只存本地文件（不落库）；学生确认/编辑后走 POST /submissions 完成诊断。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read(_PHOTO_MAX_BYTES + 1)
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
    await run_in_threadpool(
        _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, filename), data
    )
    result = await run_in_threadpool(get_provider().transcribe_image, data, file.content_type)
    return {
        "image_id": filename,
        "image_url": f"/api/uploads/{filename}",
        "question_text": result.get("question_text", ""),
        "steps": result.get("steps", []),
        "student_work_detected": result.get("student_work_detected"),
        "needs_image_review": result.get("needs_image_review"),
        "confidence": result.get("confidence"),
    }


@router.post(
    "/photo-diagnose",
    response_model=PhotoDiagnosisOut,
    summary="直接用作答原图进行视觉诊断",
)
async def photo_diagnose(
    question_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """将学生原图直接交给视觉模型逐步判对错，并将判断落入 Submission/Step/Error。

    图片无法辨认或没有学生作答时不创建 Submission/Error；手动转写/编辑入口仍由
    /photo-transcribe + /submissions 提供。
    """
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read(_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    received_at = datetime.now()

    question = _student_accessible_question(db, current, question_id)

    # 在调用视觉模型前完成提交资格检查；后续使用同一接收时间决定延迟批改模式。
    deferred_mode = deferral_svc.assert_can_submit(
        db, current, question, received_at=received_at
    )

    recognition = await run_in_threadpool(
        get_provider().diagnose_homework_image,
        data,
        file.content_type,
        _visual_question_context(question),
    )
    confidence = normalize_confidence(recognition.get("confidence", 0.0))
    visual_steps = recognition.get("steps", [])
    steps = [str(step.get("text", "")).strip() for step in visual_steps
             if isinstance(step, dict) and str(step.get("text", "")).strip()]
    if not _has_recognized_student_work(recognition, steps) or not steps:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "照片中没有识别到学生作答，没有生成错题记录。请上传包含作答过程的照片。",
        )

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    image_path = "{}_{}{}".format(
        datetime.now().strftime("%Y%m%d%H%M%S"),
        secrets.token_hex(8),
        _PHOTO_TYPES[file.content_type],
    )
    await run_in_threadpool(
        _write_uploaded_file, os.path.join(settings.UPLOAD_DIR, image_path), data
    )
    image_name = os.path.basename((file.filename or "").replace("\\", "/")) or "作业照片"

    if deferred_mode:
        submission = deferral_svc.create_deferred(
            db, current, question, steps,
            image_path=image_path, image_name=image_name,
        )
        out = deferral_svc.deferred_out(submission)
        out.update({
            "recognized_question_text": recognition.get("question_text", ""),
            "recognized_steps": steps,
            "recognition_confidence": confidence,
        })
        return out
    submission, diagnosed_steps, diagnosed_errors = diagnose_visual_submission(
        db, current, question, visual_steps
    )
    _add_submission_image_link(db, submission, image_path, image_name)
    review = review_svc.create_review_if_needed(
        db, submission,
        confidence_signals=review_svc.visual_confidence_signals(
            _visual_review_confidence(confidence, recognition), visual_steps
        ),
        commit=False,
    )
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    result = present_for_student(
        submission, db, steps=diagnosed_steps, errors=diagnosed_errors,
        review_status=review.status if review is not None else review_svc.APPROVED,
    )
    result.update({
        "recognized_question_text": recognition.get("question_text", ""),
        "recognized_steps": steps,
        "recognition_confidence": confidence,
    })
    return result


# ---------- 主页 Agent 对话（v0.3.0 新增，LangGraph；v0.6.0 改会话制） ----------
# v0.6.0 口径：对话按「会话」组织——新对话 = 新建一条会话（不再物理删除），
# 旧会话在历史列表里可找回、可单独删除。旧 chat_messages 数据首次访问时
# 自动迁移成一条「之前的对话」会话（见 services/chat_sessions.ensure_migrated）。

_AGENT_MSG_MAX = 2000
_AGENT_HISTORY_WINDOW = 20   # 组上下文时取当前会话最近 N 条
_AGENT_HISTORY_RETURN = 50   # history 接口返回当前会话最近 N 条


def _session_out(s) -> dict:
    return {
        "id": s["id"], "title": s["title"], "created_at": s["created_at"],
        "updated_at": s["updated_at"], "message_count": s["message_count"],
    }


@router.get("/agent/sessions", response_model=List[ChatSessionOut], summary="我的对话会话列表（v0.6.0 新增）")
def agent_sessions(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """历史对话列表：按最近更新倒序，含每条会话的消息数。首次访问触发旧记录迁移。"""
    from ..services import chat_sessions as cs

    return [_session_out(s) for s in cs.list_sessions(db, current)]


@router.post("/agent/sessions", response_model=ChatSessionOut, summary="新建对话会话（v0.6.0 新增）")
def agent_create_session(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """新建一条空会话并成为当前会话（标题先给「新对话」，首条消息到达时自动改标题）。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    s = cs.create_session(db, current)
    return {"id": s.id, "title": s.title, "created_at": s.created_at,
            "updated_at": s.updated_at, "message_count": 0}


@router.get("/agent/sessions/{session_id}/messages", response_model=List[AgentHistoryItem],
            summary="某会话的全部消息（v0.6.0 新增）")
def agent_session_messages(session_id: int, db: Session = Depends(get_db),
                           current: User = Depends(require_student)):
    """会话内全部消息时间正序；会话不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    session = cs.get_own_session_or_migrate(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return cs.history_items(db, current, session)


@router.post("/agent/sessions/{session_id}/assistant-message",
             summary="保存视觉模型生成的助手回复")
def agent_append_assistant_message(
    session_id: int,
    body: AgentAssistantMessageIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """图片问答与作业批改并发完成后，按顺序将助手回复写入对应会话。"""
    from ..services import chat_sessions as cs

    session = cs.get_own_session_or_migrate(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "助手回复不能为空")
    message = cs.append_message(db, session, "assistant", content)
    if body.related_mistake_error_id is not None:
        related = find_related_mistake_for_error(
            db, current.id, body.related_mistake_error_id
        )
        if related:
            cs.link_related_mistake(db, message, body.related_mistake_error_id)
    return {"id": message.id, "role": message.role, "content": message.content}


@router.delete("/agent/sessions/{session_id}", summary="删除一条对话会话（v0.6.0 新增）")
def agent_delete_session(session_id: int, db: Session = Depends(get_db),
                         current: User = Depends(require_student)):
    """删除本人的一条会话及其全部消息；不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    if not cs.delete_session(db, current, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return {"deleted": True}


@router.post("/agent/chat", summary="已停用：请使用学习助手流式接口")
def agent_chat_legacy(current: User = Depends(require_student)):
    raise HTTPException(status.HTTP_410_GONE, "此接口已停用，请改用 /api/student/agent/chat/stream")


@router.post("/agent/chat/vision/stream", summary="将图片直接交给视觉模型并流式讲解")
async def agent_vision_chat_stream(
    file: UploadFile = File(...),
    question: str = Form(default=""),
    current: User = Depends(require_student),
):
    """原图直接进入视觉模型，返回 SSE 文本块；不先 OCR 再交给文本模型。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    image_bytes = await file.read(_PHOTO_MAX_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(image_bytes) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    if len(question.strip()) > _AGENT_MSG_MAX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "问题有点长，单条最多 2000 字")
    content_type = file.content_type or "image/jpeg"
    student_id = current.id

    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n\n"

    def stream_events():
        yield ": connected\n\n"
        stream_started_at = perf_counter()
        first_text_at = None
        reply_parts = []
        image_stream = None
        try:
            image_stream = get_provider().stream_image_answer(
                image_bytes, content_type, question
            )
            for chunk in image_stream:
                if not chunk:
                    continue
                if first_text_at is None:
                    first_text_at = perf_counter()
                    logger.info(
                        "图片视觉讲解首字延迟（耗时 %.2f 秒，student_id=%s）",
                        first_text_at - stream_started_at, student_id,
                    )
                reply_parts.append(chunk)
                yield event("token", {"text": chunk})
            reply = "".join(reply_parts).strip()
            if not reply:
                raise ValueError("视觉模型没有返回讲解内容")
            logger.info(
                "图片视觉讲解流完成（总耗时 %.2f 秒，输出字符数 %d，student_id=%s）",
                perf_counter() - stream_started_at, len(reply), student_id,
            )
            yield event("done", {"reply": reply})
        except Exception:
            logger.exception("学生图片视觉讲解流中断（student_id=%s）", student_id)
            logger.warning(
                "图片视觉讲解流失败（耗时 %.2f 秒，已输出字符数 %d，student_id=%s）",
                perf_counter() - stream_started_at,
                sum(len(part) for part in reply_parts),
                student_id,
            )
            yield event("error", {"detail": "视觉模型暂时无法完成讲解，请稍后重试。"})
        finally:
            close = getattr(image_stream, "close", None)
            if close is not None:
                close()

    return ClosingStreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/chat/stream", summary="与学习助手流式对话")
def agent_chat_stream(body: AgentChatIn, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    """以 SSE 逐块返回学习助手回复，结束时写入会话并返回建议追问。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from ..agent.graph import agent_reply_stream
    from ..agent.suggestions import student_suggestions
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
        # 先提交用户消息；浏览器刷新或流中断时，至少保留本轮提问。
        cs.append_message(db, session, "user", text)

    preloaded_related_mistake = None
    if body.safe_tools_only and body.related_mistake_error_id is not None:
        # 重新校验当前学生与错题的归属，不能通过客户端传入的 ID 读取他人记录。
        preloaded_related_mistake = find_related_mistake_for_error(
            db, current.id, body.related_mistake_error_id
        )

    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n\n"

    def failure_detail(exc: Exception, homework_saved: bool) -> str:
        """把常见模型故障转成可操作提示，不把上游响应或凭证信息暴露给学生。"""
        chain = []
        current = exc
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__

        if any("timeout" in type(item).__name__.lower() for item in chain):
            if homework_saved:
                return "学习助手等待模型响应超时。批改记录已保存，可以点击“重试讲解”，无需重新上传。"
            return "学习助手等待模型响应超时，请稍后重试。"

        status_code = next((
            getattr(item, "status_code", None)
            or getattr(getattr(item, "response", None), "status_code", None)
            for item in chain
            if getattr(item, "status_code", None)
            or getattr(getattr(item, "response", None), "status_code", None)
        ), None)
        if status_code == 429:
            if homework_saved:
                return "学习助手当前请求较多。批改记录已保存，请稍后点击“重试讲解”。"
            return "学习助手当前请求较多，请稍后重试。"
        if status_code in (401, 403):
            if homework_saved:
                return "学习助手模型服务暂不可用。批改记录已保存，请稍后重试。"
            return "学习助手模型服务暂不可用，请稍后重试。"
        if isinstance(status_code, int) and status_code >= 500:
            if homework_saved:
                return "学习助手模型服务暂时繁忙。批改记录已保存，请稍后点击“重试讲解”。"
            return "学习助手模型服务暂时繁忙，请稍后重试。"
        if homework_saved:
            return "学习助手暂时无法生成讲解。批改记录已保存，可以点击“重试讲解”，无需重新上传。"
        return "学习助手暂时无法生成回复，请稍后重试。"

    def stream_events():
        yield ": connected\n\n"
        reply_stream = agent_reply_stream(
            db, current, history, text, safe_tools_only=body.safe_tools_only
        )
        try:
            while True:
                try:
                    chunk = next(reply_stream)
                except StopIteration as stopped:
                    result = stopped.value
                    break
                yield event("token", {"text": chunk})

            reply = result["reply"]
            assistant_message = cs.append_message(db, session, "assistant", reply)
            related_mistake = result.get("related_mistake") or preloaded_related_mistake
            if related_mistake:
                cs.link_related_mistake(db, assistant_message, related_mistake.get("id"))
            yield event("done", {
                "reply": reply,
                "suggestions": student_suggestions(text, result.get("tools_used")),
                "session_id": session.id,
                "related_mistake": related_mistake,
            })
        except Exception as exc:
            logger.exception(
                "学生学习助手流式回复中断（session_id=%s, safe_tools_only=%s）",
                session.id, body.safe_tools_only,
            )
            yield event("error", {"detail": failure_detail(exc, body.safe_tools_only)})
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


@router.get("/agent/history", response_model=List[AgentHistoryItem], summary="我的对话历史")
def agent_history(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """兼容旧用法：返回「当前会话」最近 50 条消息（v0.6.0 起按会话隔离）。"""
    from ..services import chat_sessions as cs

    session = cs.current_session_or_migrate(db, current)
    if session is None:
        return []
    return cs.history_items(db, current, session, limit=_AGENT_HISTORY_RETURN)


@router.post("/agent/new-session", response_model=ChatSessionOut, summary="开始新对话（v0.6.0 改为新建会话）")
def agent_new_session(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """「新对话」（v0.6.0 语义变更）：新建一条会话并设为当前，旧会话保留在历史
    列表里可找回（取代 v0.5.0 的物理删除口径，不再删任何东西）。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    s = cs.create_session(db, current)
    return {"id": s.id, "title": s.title, "created_at": s.created_at,
            "updated_at": s.updated_at, "message_count": 0}


# ---------- 站内提醒（v0.3.0 新增） ----------

@router.get("/notifications/unread-count", response_model=NotificationUnreadCountOut,
            summary="我的提醒未读数（导航角标）")
def unread_notification_count(db: Session = Depends(get_db), current: User = Depends(require_student)):
    count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current.id,
        Notification.is_read.is_(False),
    ).scalar()
    return {"unread_count": int(count or 0)}


@router.get("/notifications", response_model=NotificationListOut, summary="我的提醒列表")
def my_notifications(db: Session = Depends(get_db), current: User = Depends(require_student)):
    unread_notification = aliased(Notification)
    unread_count = db.query(func.count(unread_notification.id)).filter(
        unread_notification.user_id == current.id,
        unread_notification.is_read.is_(False),
    ).scalar_subquery()
    rows = (
        db.query(Notification, unread_count.label("unread_count"))
        .filter(Notification.user_id == current.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(30)
        .all()
    )
    items = [
        NotificationItem(
            id=n.id, type=n.type, content=n.content,
            related_submission_id=n.related_submission_id,
            is_read=n.is_read, created_at=n.created_at,
        )
        for n, _ in rows
    ]
    unread = int(rows[0].unread_count or 0) if rows else 0
    return {"unread_count": unread, "items": items}


@router.post("/notifications/read", response_model=NotificationReadOut, summary="提醒标已读")
def mark_notifications_read(body: NotificationReadIn, db: Session = Depends(get_db),
                            current: User = Depends(require_student)):
    """ids 不传/为空 = 全部标已读；传 ids 只标这些（且只限本人的）。"""
    query = db.query(Notification).filter(
        Notification.user_id == current.id, Notification.is_read.is_(False)
    )
    if body.ids:
        notification_ids = list(dict.fromkeys(body.ids))
        updated = 0
        for start in range(0, len(notification_ids), 500):
            updated += query.filter(
                Notification.id.in_(notification_ids[start:start + 500])
            ).update({Notification.is_read: True}, synchronize_session=False)
    else:
        updated = query.update(
            {Notification.is_read: True}, synchronize_session=False
        )
    db.commit()
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == current.id, Notification.is_read.is_(False))
        .count()
    )
    return {"updated": updated, "unread_count": unread}
