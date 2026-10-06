# /api/student/* 学生端
import os
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import require_student
from ..config import settings
from ..database import get_db
from ..models import Assignment, Correction, Error, Essay, Question, Submission, User
from ..schemas import (
    AssignmentDetail,
    BriefingOut,
    CorrectionCreate,
    CorrectionOut,
    DiagnosisOut,
    EssayBrief,
    EssayCreate,
    EssayOut,
    PhotoTranscribeOut,
    ProfileOut,
    QuestionOut,
    SubjectReportOut,
    KnowledgePointErrorItem,
    SubmissionBrief,
    SubmissionCreate,
)
from ..services.diagnosis import diagnose_submission, present_diagnosis, present_error, verify_correction
from ..services.essays import present_essay, score_and_save_essay
from ..services.providers import get_provider
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_profile,
    student_report,
)

router = APIRouter(prefix="/api/student", tags=["student"])


# ---------- 作业 ----------

@router.get("/assignments", summary="作业列表")
def list_assignments(db: Session = Depends(get_db), current: User = Depends(require_student)):
    items = db.query(Assignment).order_by(Assignment.id).all()
    result = []
    for a in items:
        qc = db.query(Question).filter(Question.assignment_id == a.id).count()
        result.append({
            "id": a.id, "title": a.title, "description": a.description,
            "question_count": qc, "created_at": a.created_at,
        })
    return {"total": len(result), "items": result}


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetail, summary="作业详情")
def assignment_detail(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_student)):
    a = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    questions = (
        db.query(Question).filter(Question.assignment_id == a.id)
        .order_by(Question.order_num, Question.id).all()
    )
    return AssignmentDetail(
        id=a.id, title=a.title, description=a.description,
        questions=[QuestionOut.model_validate(q) for q in questions],
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
    submission, steps, errors = diagnose_submission(db, current, q, data.steps)
    return present_diagnosis(submission, db)


@router.get("/submissions", summary="我的提交记录")
def list_submissions(question_id: Optional[int] = Query(default=None),
                     limit: int = Query(default=20, le=100), offset: int = Query(default=0, ge=0),
                     db: Session = Depends(get_db), current: User = Depends(require_student)):
    query = db.query(Submission).filter(Submission.student_id == current.id)
    if question_id:
        query = query.filter(Submission.question_id == question_id)
    total = query.count()
    subs = query.order_by(Submission.submitted_at.desc()).offset(offset).limit(limit).all()
    items = []
    for s in subs:
        err_n = db.query(Error).filter(Error.submission_id == s.id).count()
        items.append(SubmissionBrief(
            id=s.id, question_id=s.question_id,
            question_stem=s.question.stem if s.question else "",
            knowledge_point=s.question.knowledge_point if s.question else "",
            status=s.status, error_count=err_n, submitted_at=s.submitted_at,
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
    return present_diagnosis(s, db)


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
    is_correct, note = verify_correction(db, err, body.content.strip())
    c = Correction(error_id=err.id, student_id=current.id,
                   content=body.content.strip(), is_correct=is_correct, note=note)
    db.add(c)
    db.commit()
    db.refresh(c)
    return CorrectionOut.model_validate(c)


# ---------- 画像 ----------

@router.get("/profile", response_model=ProfileOut, summary="我的学习画像")
def my_profile(db: Session = Depends(get_db), current: User = Depends(require_student)):
    return student_profile(db, current)


# ---------- 首页简报 / 拍照转写（v0.2.0 新增） ----------

@router.get("/briefing", response_model=BriefingOut, summary="首页待办简报")
def briefing(db: Session = Depends(get_db), current: User = Depends(require_student)):
    return student_briefing(db, current)


# ---------- 学习报告（v0.2.1 新增）：科目 → 知识点 → 错题时间线 → 步骤诊断 ----------

@router.get("/report", response_model=List[SubjectReportOut], summary="我的学习报告（按科目）")
def my_report(db: Session = Depends(get_db), current: User = Depends(require_student)):
    return student_report(db, current)


@router.get(
    "/report/knowledge-points/{kp_name}/errors",
    response_model=List[KnowledgePointErrorItem],
    summary="知识点错题时间线",
)
def my_knowledge_point_errors(kp_name: str, db: Session = Depends(get_db),
                              current: User = Depends(require_student)):
    return knowledge_point_errors(db, current, kp_name)


_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp"}
_PHOTO_MAX_BYTES = 10 * 1024 * 1024


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
    result = get_provider().transcribe_image(data, file.content_type)
    return {
        "image_id": filename,
        "image_url": f"/api/uploads/{filename}",
        "question_text": result.get("question_text", ""),
        "steps": result.get("steps", []),
    }
