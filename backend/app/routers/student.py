# /api/student/* 学生端
import json
import os
import re
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..auth import require_student
from ..config import settings
from ..database import get_db
from ..models import (
    Assignment,
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
    User,
    Verification,
)
from ..schemas import (
    AgentChatIn,
    AgentChatOut,
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
    NotificationReadIn,
    NotificationReadOut,
    PhotoDiagnosisOut,
    PhotoReviewOut,
    PhotoCaptureSaveIn,
    PhotoTranscribeOut,
    ProfileOut,
    QuestionOut,
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
    VerificationCreate,
    VerificationOut,
    VerificationSubmitIn,
    VerificationSubmitOut,
)
from ..services import variant_gen
from ..services import deferral as deferral_svc
from ..services import reviews as review_svc
from ..services import scoring as scoring_svc
from ..services.diagnosis import diagnose_submission, present_diagnosis, present_error, verify_correction
from ..services.answer_check import (
    student_visible_linear_error_detail,
    student_visible_reference_answer,
    student_visible_solution_steps,
)
from ..services.essays import present_essay, score_and_save_essay
from ..services.providers import get_provider
from ..services.stats import (
    assignment_ext_fields,
    knowledge_point_errors,
    student_briefing,
    student_profile,
    student_report,
)

router = APIRouter(prefix="/api/student", tags=["student"])


# ---------- 教师审核可见性（v0.9.0）：学生侧统一出口 ----------
# AI 批改完先过教师审核：pending 的提交对学生只返回占位（status=pending_review），
# 不含 steps/errors 等任何诊断结论；无审核行的历史/种子提交视为 approved 全量可见。

def present_for_student(submission: Submission, db: Session) -> dict:
    """学生侧诊断出参（提交/详情/拍照批改共用）：待审核 → 占位；已通过 → 完整诊断。"""
    if review_svc.review_status(db, submission.id) == review_svc.PENDING:
        return {
            "submission_id": submission.id,
            "question_id": submission.question_id,
            "status": "pending_review",
            "first_error_seq": None,
            "steps": [],
            "errors": [],
            "follow_up_question": None,
            "review_status": "pending",
            # 评分系统：分数跟诊断一起过审，待审核时不下发
            "score": None,
        }
    out = present_diagnosis(submission, db)
    out["review_status"] = "approved"
    # 评分系统：已通过才带本题得分（最终分/满分）+ 该作业累计；算不出时为 None
    vis = scoring_svc.visible_score(db, submission)
    if vis is not None and submission.question is not None:
        vis.update(scoring_svc.assignment_progress(
            db, submission.student_id, submission.question.assignment_id))
    out["score"] = vis
    return out


# ---------- 作业 ----------

@router.get("/assignments", summary="作业列表")
def list_assignments(db: Session = Depends(get_db), current: User = Depends(require_student)):
    items = (db.query(Assignment)
             .filter((Assignment.created_by.is_(None)) | (~Assignment.created_by.in_(
                 db.query(User.id).filter(User.role == "student")
             )))
             .order_by(Assignment.id).all())
    result = []
    for a in items:
        qids = [row[0] for row in
                db.query(Question.id).filter(Question.assignment_id == a.id).all()]
        # v0.13.9：该学生在这份作业里已提交的题数（去重到题）——交作业页的
        # 「正在交的作业」下拉据此把已全部交完的作业滤掉，不再列出来
        submitted = (
            db.query(Submission.question_id)
            .filter(Submission.student_id == current.id,
                    Submission.question_id.in_(qids))
            .distinct().count()
        ) if qids else 0
        result.append({
            "id": a.id, "title": a.title, "description": a.description,
            "question_count": len(qids), "submitted_count": submitted,
            "created_at": a.created_at,
            # v0.5.0：发布模式与线下作业信息（mode/workbook_title/page_range/deadline）
            **assignment_ext_fields(db, a.id),
        })
    return {"total": len(result), "items": result}


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail, summary="作业详情")
def assignment_detail(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    a = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    creator = db.query(User).filter(User.id == a.created_by).first() if a and a.created_by else None
    if not a or (creator and creator.role == "student"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    questions = (
        db.query(Question).filter(Question.assignment_id == a.id)
        .order_by(Question.order_num, Question.id).all()
    )
    # v0.13.1：大题分组（成员映射 + 大题列表）
    members = (
        db.query(QuestionGroupMember)
        .filter(QuestionGroupMember.question_id.in_([q.id for q in questions])).all()
        if questions else []
    )
    group_by_qid = {m.question_id: m.group_id for m in members}
    groups = (
        db.query(QuestionGroup).filter(QuestionGroup.assignment_id == a.id)
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
            {"id": g.id, "stem": g.stem, "order_num": g.order_num} for g in groups
        ],
        **assignment_ext_fields(db, a.id),
    )


# ---------- 数学诊断 ----------

@router.post("/submissions", response_model=DiagnosisOut, summary="提交数学作业并诊断")
def submit_math(data: SubmissionCreate, db: Session = Depends(get_db),
               current: User = Depends(require_student)):
    q = db.query(Question).filter(Question.id == data.question_id).first()
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
    if q.subject != "math":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该题是作文题，请使用 /api/student/essays 提交")
    # v0.13.1：提交锁定（每题一次）+ 延迟批改窗口（允许修改的作业截止前只收不批）
    deferral_svc.assert_can_submit(db, current, q)
    if deferral_svc.is_deferred_mode(db, q.assignment_id):
        return deferral_svc.deferred_out(deferral_svc.create_deferred(db, current, q, data.steps))
    submission, steps, errors = diagnose_submission(db, current, q, data.steps)
    # v0.9.0：新提交先进教师审核队列，学生先看到「待老师审核」占位
    review_svc.create_pending_review(db, submission)
    return present_for_student(submission, db)


@router.get("/submissions", summary="我的提交记录")
def list_submissions(question_id: Optional[int] = Query(default=None),
                     limit: int = Query(default=20, le=100), offset: int = Query(default=0, ge=0),
                     db: Session = Depends(get_db), current: User = Depends(require_student)):
    query = db.query(Submission).filter(Submission.student_id == current.id)
    if question_id:
        query = query.filter(Submission.question_id == question_id)
    total = query.count()
    subs = query.order_by(Submission.submitted_at.desc()).offset(offset).limit(limit).all()
    status_by_id = review_svc.review_status_map(db, [s.id for s in subs])
    items = []
    for s in subs:
        rstatus = status_by_id.get(s.id, review_svc.APPROVED)
        # v0.9.0：待审核的提交不向学生泄露错误数（诊断结论不可见）
        err_n = 0 if rstatus == review_svc.PENDING else db.query(Error).filter(Error.submission_id == s.id).count()
        # 评分系统：已通过的提交带最终分与本题满分；待审核不给分
        score = max_score = None
        if rstatus != review_svc.PENDING:
            vis = scoring_svc.visible_score(db, s)
            if vis:
                score, max_score = vis["score"], vis["max_score"]
        items.append(SubmissionBrief(
            id=s.id, question_id=s.question_id,
            question_stem=s.question.stem if s.question else "",
            knowledge_point=s.question.knowledge_point if s.question else "",
            status=s.status, error_count=err_n, submitted_at=s.submitted_at,
            review_status=rstatus,
            score=score, max_score=max_score,
        ))
    return {"total": total, "items": items}


@router.get("/submissions/{submission_id}", response_model=DiagnosisOut, summary="提交详情")
def submission_detail(submission_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提交记录不存在")
    if s.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能查看自己的提交记录")
    return present_for_student(s, db)


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
def my_mistakes(archived: bool = Query(default=False), db: Session = Depends(get_db),
                current: User = Depends(require_student)):
    """List this student's active or archived error occurrences without deleting diagnosis history."""
    all_rows = (
        db.query(Error, Submission, Question, Assignment, Step)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .join(Assignment, Question.assignment_id == Assignment.id)
        .outerjoin(Step, Error.step_id == Step.id)
        .filter(Submission.student_id == current.id)
        .order_by(Error.created_at.desc(), Error.id.desc())
        .all()
    )
    # v0.9.0：待教师审核提交产生的错题先不进错题本（通过后自动出现）；
    # 学生自助收录的 captures 不走批改管线，不受影响（下方单独拼装）。
    pending_sub_ids = review_svc.pending_submission_ids(db, current.id)
    if pending_sub_ids:
        all_rows = [row for row in all_rows if row[1].id not in pending_sub_ids]
    error_ids = [error.id for error, _, _, _, _ in all_rows]
    archived_at_by_error = {
        item.error_id: item.archived_at
        for item in db.query(StudentMistakeArchive)
        .filter(StudentMistakeArchive.student_id == current.id,
                StudentMistakeArchive.error_id.in_(error_ids))
        .all()
    }
    rows = [row for row in all_rows if (row[0].id in archived_at_by_error) == archived]
    assignment_ids = {assignment.id for _, _, _, assignment, _ in all_rows}
    visible_error_ids = [error.id for error, _, _, _, _ in rows]
    reviewed = {
        (item.assignment_id, item.category_key)
        for item in db.query(StudentMistakeCategoryReview)
        .filter(StudentMistakeCategoryReview.student_id == current.id,
                StudentMistakeCategoryReview.assignment_id.in_(assignment_ids))
        .all()
    }
    correction_by_error = {}
    for correction in (
        db.query(Correction)
        .filter(Correction.student_id == current.id, Correction.error_id.in_(visible_error_ids))
        .order_by(Correction.submitted_at.desc(), Correction.id.desc())
        .all()
    ):
        correction_by_error.setdefault(correction.error_id, correction)
    verification_by_error = {}
    for verification in (
        db.query(Verification)
        .filter(Verification.student_id == current.id,
                Verification.source_error_id.in_(visible_error_ids))
        .order_by(Verification.created_at.desc(), Verification.id.desc())
        .all()
    ):
        verification_by_error.setdefault(verification.source_error_id, verification)

    history_by_category = {}
    for error, submission, question, assignment, _ in all_rows:
        key, _ = _mistake_category(question.subject, error.error_type, error.knowledge_point)
        history_by_category.setdefault(key, []).append((error, submission, question, assignment))

    result = []
    for error, submission, question, assignment, step in rows:
        category_key, category_label = _mistake_category(
            question.subject, error.error_type, error.knowledge_point
        )
        previous_by_assignment = {}
        for previous_error, previous_submission, previous_question, previous_assignment in history_by_category.get(category_key, []):
            if previous_assignment.id == assignment.id or previous_assignment.created_at >= assignment.created_at:
                continue
            previous_by_assignment.setdefault(previous_assignment.id, {
                "id": previous_error.id,
                "submission_id": previous_submission.id,
                "assignment_id": previous_assignment.id,
                "assignment_title": previous_assignment.title,
                "assignment_created_at": previous_assignment.created_at,
                "question_stem": previous_question.stem,
            })
        correction = correction_by_error.get(error.id)
        verification = verification_by_error.get(error.id)
        correct_answer = (
            student_visible_reference_answer(question.stem, question.standard_answer)
            if question.subject == "math" else question.standard_answer
        )
        result.append(StudentMistakeOut(
            id=error.id,
            submission_id=submission.id,
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
                student_visible_solution_steps(question.stem)
                if question.subject == "math" and correct_answer else []
            ),
            knowledge_point=error.knowledge_point,
            error_type=error.error_type,
            is_stubborn=error.is_stubborn,
            detail=(
                student_visible_linear_error_detail(
                    question.stem, step.text if step else None, step.seq if step else None
                ) or error.detail
            ),
            step_seq=step.seq if step else None,
            step_text=step.text if step else None,
            created_at=error.created_at,
            submitted_at=submission.submitted_at,
            category_key=category_key,
            category_label=category_label,
            category_studied=(assignment.id, category_key) in reviewed,
            archived_at=archived_at_by_error.get(error.id),
            similar_occurrences=list(previous_by_assignment.values())[:5],
            latest_correction=({
                "id": correction.id,
                "content": correction.content,
                "is_correct": correction.is_correct,
                "note": correction.note,
                "submitted_at": correction.submitted_at,
            } if correction else None),
            verification_status=verification.status if verification else None,
        ))
    captures = (
        db.query(StudentQuestionCapture)
        .filter(StudentQuestionCapture.student_id == current.id,
                StudentQuestionCapture.saved_at.isnot(None))
        .order_by(StudentQuestionCapture.created_at.desc(), StudentQuestionCapture.id.desc())
        .all()
    )
    for capture in captures:
        if (capture.archived_at is not None) != archived:
            continue
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
            image_url=f"/api/uploads/{capture.image_path}",
        ))
    result.sort(key=lambda item: item.created_at, reverse=True)
    return result


@router.patch("/mistakes/categories", summary="标记错因类别学习状态")
def set_mistake_category_studied(body: MistakeCategoryStudyIn,
                                 db: Session = Depends(get_db),
                                 current: User = Depends(require_student)):
    rows = (
        db.query(Error, Question)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(Submission.student_id == current.id, Question.assignment_id == body.assignment_id)
        .all()
    )
    archived_ids = {
        item.error_id for item in db.query(StudentMistakeArchive)
        .filter(StudentMistakeArchive.student_id == current.id).all()
    }
    active_rows = [(error, question) for error, question in rows if error.id not in archived_ids]
    valid_keys = {
        _mistake_category(question.subject, error.error_type, error.knowledge_point)[0]
        for error, question in active_rows
    }
    if body.category_key not in valid_keys:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业或错题类别不存在")

    state = db.query(StudentMistakeCategoryReview).filter_by(
        student_id=current.id,
        assignment_id=body.assignment_id,
        category_key=body.category_key,
    ).first()
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

    error = (
        db.query(Error).join(Submission, Error.submission_id == Submission.id)
        .filter(Error.id == error_id, Submission.student_id == current.id)
        .first()
    )
    if not error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到这条错题记录")
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
    _record_mistake_event(db, current.id, error.submission.question.assignment_id, event_type, payload, now)
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

    rows = (
        db.query(Error, Question)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(Submission.student_id == current.id, Question.assignment_id == assignment_id)
        .all()
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业没有可整理的错题")

    error_ids = [error.id for error, _ in rows]
    archive_states = db.query(StudentMistakeArchive).filter(
        StudentMistakeArchive.student_id == current.id,
        StudentMistakeArchive.error_id.in_(error_ids),
    ).all()
    archived_by_error = {state.error_id: state for state in archive_states}

    if body.archived:
        active_rows = [(error, question) for error, question in rows if error.id not in archived_by_error]
        if not active_rows:
            return {"assignment_id": assignment_id, "archived_ids": []}
        categories = {
            _mistake_category(question.subject, error.error_type, error.knowledge_point)[0]
            for error, question in active_rows
        }
        reviewed = {
            item.category_key for item in db.query(StudentMistakeCategoryReview)
            .filter_by(student_id=current.id, assignment_id=assignment_id).all()
        }
        remaining = categories - reviewed
        if remaining:
            raise HTTPException(status.HTTP_409_CONFLICT, f"还有 {len(remaining)} 类错误没有标记为已学习。")
        now = datetime.now()
        archived_ids = [error.id for error, _ in active_rows]
        db.add_all(StudentMistakeArchive(student_id=current.id, error_id=error_id, archived_at=now)
                    for error_id in archived_ids)
        _record_mistake_event(db, current.id, assignment_id, "mistake_assignment_archived",
                              {"student_id": current.id, "occurrence_ids": archived_ids}, now)
        db.commit()
        return {"assignment_id": assignment_id, "archived_ids": archived_ids, "archived_at": now}

    occurrence_ids = list(dict.fromkeys(body.occurrence_ids))
    if not occurrence_ids:
        return {"assignment_id": assignment_id, "archived_ids": []}
    restore_states = (
        db.query(StudentMistakeArchive)
        .join(Error, StudentMistakeArchive.error_id == Error.id)
        .join(Submission, Error.submission_id == Submission.id)
        .join(Question, Submission.question_id == Question.id)
        .filter(
            StudentMistakeArchive.student_id == current.id,
            StudentMistakeArchive.error_id.in_(occurrence_ids),
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
        question = db.query(Question).filter(Question.id == body.question_id).first()
        if not question:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
        if question.subject != "english":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该题不是作文题")
    return score_and_save_essay(db, current, body.text.strip(), question)


@router.get("/essays", summary="我的作文列表")
def list_essays(limit: int = Query(default=20, le=100), offset: int = Query(default=0, ge=0),
                db: Session = Depends(get_db), current: User = Depends(require_student)):
    import json
    query = db.query(Essay).filter(Essay.student_id == current.id)
    total = query.count()
    essays = query.order_by(Essay.submitted_at.desc()).offset(offset).limit(limit).all()
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
    err = db.query(Error).filter(Error.id == body.error_id).first()
    if not err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    sub = db.query(Submission).filter(Submission.id == err.submission_id).first()
    if not sub or sub.student_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能订正自己的错误")
    # v0.9.0：所属提交还在等老师审核时，错题对学生不可见，自然也不能订正
    if review_svc.review_status(db, sub.id) == review_svc.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "老师审核通过后就可以订正这道题啦")
    is_correct, note = verify_correction(db, err, body.content.strip())
    c = Correction(error_id=err.id, student_id=current.id,
                   content=body.content.strip(), is_correct=is_correct, note=note)
    db.add(c)
    db.commit()
    db.refresh(c)
    out = CorrectionOut.model_validate(c)
    # v0.4.0：订正成功 → 提示可去做二次验证（通过验证才算知识点已修复）
    out.can_verify = is_correct is True
    out.knowledge_point = err.knowledge_point
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
        err = db.query(Error).filter(Error.id == source_error_id).first()
        sub = db.query(Submission).filter(Submission.id == err.submission_id).first() if err else None
        if not err or not sub or sub.student_id != current.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_error_id 不是你的错题记录")
        # v0.9.0：待审核提交的错题对学生不可见，不能拿来发起验证
        if review_svc.review_status(db, sub.id) == review_svc.PENDING:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "老师审核通过后就可以来验证啦")
    else:
        pending_sub_ids = review_svc.pending_submission_ids(db, current.id)
        latest_query = (
            db.query(Error)
            .join(Submission, Error.submission_id == Submission.id)
            .filter(Submission.student_id == current.id, Error.knowledge_point == kp)
        )
        if pending_sub_ids:
            latest_query = latest_query.filter(~Error.submission_id.in_(pending_sub_ids))
        latest = latest_query.order_by(Error.created_at.desc(), Error.id.desc()).first()
        source_error_id = latest.id if latest else None

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
    db.commit()
    db.refresh(v)
    return _verification_out(v)


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
    db.commit()
    db.refresh(v)
    return {
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


@router.post("/photo-review", response_model=PhotoReviewOut, summary="识别题目图片并按作答情况分流")
async def photo_review(
    file: UploadFile = File(...),
    question_id: Optional[int] = Form(default=None),
    question_context: str = Form(default=""),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """没有学生作答时只进入问答，并暂存图片供学生之后主动收录；有作答时复用数学诊断。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")

    question = None
    if question_id is not None:
        question = db.query(Question).filter(Question.id == question_id).first()
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
        if question.subject != "math":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "原图自动诊断目前仅支持数学题")
    context = question.stem if question else question_context
    recognition = await run_in_threadpool(
        get_provider().transcribe_image, data, file.content_type, context, question is None
    )
    confidence = float(recognition.get("confidence", 0.0) or 0.0)
    if recognition.get("needs_image_review") or confidence < 0.45:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "照片暂时无法可靠辨认，没有生成错题记录。请拍清楚后重试。",
        )

    question_text = str(recognition.get("question_text", "")).strip() or (question.stem if question else "")
    steps = [str(step).strip() for step in recognition.get("steps", []) if str(step).strip()]
    has_work = bool(recognition.get("student_work_detected", bool(steps)))
    if not has_work:
        if not question_text:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "没有识别到题目内容，请拍清楚题干后重试。",
            )
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        filename = "{}_{}{}".format(
            datetime.now().strftime("%Y%m%d%H%M%S"),
            secrets.token_hex(4),
            _PHOTO_TYPES[file.content_type],
        )
        with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as image_file:
            image_file.write(data)
        capture = StudentQuestionCapture(
            student_id=current.id,
            question_id=question.id if question else None,
            subject=question.subject if question else "math",
            question_text=question_text,
            image_path=filename,
        )
        db.add(capture)
        db.commit()
        db.refresh(capture)
        return {"mode": "answer", "question_text": question_text, "steps": [],
                "capture_id": capture.id, "diagnosis": None}

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
            subject="math",
            knowledge_point="自主上传题",
            stem=question_text,
            order_num=1,
        )
        db.add(question)
        db.flush()

    submission, _, _ = diagnose_submission(db, current, question, steps)
    # v0.9.0：拍照批改同样先进教师审核队列，学生先看到待审核占位
    review_svc.create_pending_review(db, submission)
    diagnosis = present_for_student(submission, db)
    return {"mode": "diagnosis", "question_text": question_text,
            "steps": steps, "capture_id": None, "diagnosis": diagnosis}


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
    db.commit()
    return {"capture_id": capture.id, "saved": True, "saved_at": capture.saved_at}


@router.post("/photo-transcribe", response_model=PhotoTranscribeOut, summary="拍照转写作业")
async def photo_transcribe(file: UploadFile = File(...),
                           current: User = Depends(require_student)):
    """上传作业照片 → Provider 视觉转写 → 返回 {image_id, image_url, question_text, steps}。
    图片只存本地文件（不落库）；学生确认/编辑后走 POST /submissions 完成诊断。"""
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
    summary="直接用作答原图进行数学诊断",
)
async def photo_diagnose(
    question_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    """将学生原图送入视觉 Provider，识别证据充分后复用 Remedi 数学分步诊断。

    不清晰或没有学生作答时不创建 Submission/Error，避免把题目本身或识别噪声
    写进错题本。手动转写/编辑入口仍由 /photo-transcribe + /submissions 提供。
    """
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")

    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
    if question.subject != "math":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前原图诊断入口仅支持数学题")

    recognition = await run_in_threadpool(
        get_provider().transcribe_image,
        data,
        file.content_type,
        question.stem,
    )
    confidence = float(recognition.get("confidence", 0.0) or 0.0)
    steps = [str(step).strip() for step in recognition.get("steps", []) if str(step).strip()]
    if recognition.get("needs_image_review") or confidence < 0.45:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "这张照片暂时无法可靠辨认，没有生成错题记录。请拍清楚题目和作答过程后重试。",
        )
    if not recognition.get("student_work_detected", bool(steps)) or not steps:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "照片中没有识别到学生作答，没有生成错题记录。请上传包含作答过程的照片。",
        )

    # v0.13.1：拍照批改同链——提交锁定 + 延迟批改窗口
    deferral_svc.assert_can_submit(db, current, question)
    if deferral_svc.is_deferred_mode(db, question.assignment_id):
        submission = deferral_svc.create_deferred(db, current, question, steps)
        out = deferral_svc.deferred_out(submission)
        out.update({
            "recognized_question_text": recognition.get("question_text", ""),
            "recognized_steps": steps,
            "recognition_confidence": confidence,
        })
        return out
    submission, _, _ = diagnose_submission(db, current, question, steps)
    # v0.9.0：原图批改同样先进教师审核队列
    review_svc.create_pending_review(db, submission)
    result = present_for_student(submission, db)
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

    cs.ensure_migrated(db, current)
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

    cs.ensure_migrated(db, current)
    session = cs.get_own_session(db, current, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in cs.session_messages(db, session)
    ]


@router.delete("/agent/sessions/{session_id}", summary="删除一条对话会话（v0.6.0 新增）")
def agent_delete_session(session_id: int, db: Session = Depends(get_db),
                         current: User = Depends(require_student)):
    """删除本人的一条会话及其全部消息；不存在或不是本人的统一 404。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    if not cs.delete_session(db, current, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在")
    return {"deleted": True}


@router.post("/agent/chat", response_model=AgentChatOut, summary="与学习助手对话")
def agent_chat(body: AgentChatIn, db: Session = Depends(get_db),
               current: User = Depends(require_student)):
    """学生主页自由对话（v0.6.0 会话制）：解析目标会话（body.session_id 指定 /
    缺省取当前会话，没有则自动新建）→ 只取该会话最近 20 条组上下文 → 跑 Agent 图
    （或规则兜底）→ 两条消息写入该会话 → 返回回复 + 建议追问。会话间上下文隔离。
    LLM 异常在 Agent 层已降级，不会 500。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from ..agent.graph import agent_reply_full
    from ..agent.suggestions import student_suggestions
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
        HumanMessage(content=r.content) if r.role == "user" else AIMessage(content=r.content)
        for r in rows
    ]
    result = agent_reply_full(db, current, history, text)
    reply = result["reply"]

    cs.append_message(db, session, "user", text)
    cs.append_message(db, session, "assistant", reply)
    return {
        "reply": reply,
        "suggestions": student_suggestions(text, result.get("tools_used")),
        "session_id": session.id,
    }


@router.get("/agent/history", response_model=List[AgentHistoryItem], summary="我的对话历史")
def agent_history(db: Session = Depends(get_db), current: User = Depends(require_student)):
    """兼容旧用法：返回「当前会话」最近 50 条消息（v0.6.0 起按会话隔离）。"""
    from ..services import chat_sessions as cs

    cs.ensure_migrated(db, current)
    session = cs.current_session(db, current)
    if session is None:
        return []
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in cs.session_messages(db, session, limit=_AGENT_HISTORY_RETURN)
    ]


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

@router.get("/notifications", response_model=NotificationListOut, summary="我的提醒列表")
def my_notifications(db: Session = Depends(get_db), current: User = Depends(require_student)):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(30)
        .all()
    )
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == current.id, Notification.is_read.is_(False))
        .count()
    )
    items = [
        NotificationItem(
            id=n.id, type=n.type, content=n.content,
            related_submission_id=n.related_submission_id,
            is_read=n.is_read, created_at=n.created_at,
        )
        for n in rows
    ]
    return {"unread_count": unread, "items": items}


@router.post("/notifications/read", response_model=NotificationReadOut, summary="提醒标已读")
def mark_notifications_read(body: NotificationReadIn, db: Session = Depends(get_db),
                            current: User = Depends(require_student)):
    """ids 不传/为空 = 全部标已读；传 ids 只标这些（且只限本人的）。"""
    query = db.query(Notification).filter(
        Notification.user_id == current.id, Notification.is_read.is_(False)
    )
    if body.ids:
        query = query.filter(Notification.id.in_(body.ids))
    targets = query.all()
    for n in targets:
        n.is_read = True
    db.commit()
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == current.id, Notification.is_read.is_(False))
        .count()
    )
    return {"updated": len(targets), "unread_count": unread}
