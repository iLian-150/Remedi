# /api/teacher/* 教师端
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth import require_teacher
from ..database import get_db
from ..models import Assignment, Error, Essay, Question, Submission, User
from ..schemas import (
    ErrorCorrectIn,
    KnowledgePointRankItem,
    ProfileOut,
    QuestionOut,
    StudentBrief,
    TeacherAssignmentCreate,
    TeacherAssignmentOut,
    TeacherAssignmentQuestionOut,
    TeacherErrorItem,
    TopQuestionItem,
    UserOut,
)
from ..services.diagnosis import present_error
from ..services.stats import knowledge_point_ranking, list_students, student_profile, top_error_questions

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

ERROR_TYPES = ("计算失误", "概念混淆", "审题遗漏", "无法解析")


def _teacher_error_item(err: Error, db: Session) -> TeacherErrorItem:
    sub = db.query(Submission).filter(Submission.id == err.submission_id).first()
    student = db.query(User).filter(User.id == sub.student_id).first() if sub else None
    question = db.query(Question).filter(Question.id == sub.question_id).first() if sub else None
    base = present_error(err, db)
    return TeacherErrorItem(
        id=base["id"],
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
    total = query.count()
    errs = query.order_by(Error.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_teacher_error_item(e, db) for e in errs]}


@router.post("/errors/{error_id}/correct", response_model=TeacherErrorItem, summary="教师一键纠错")
def correct_error(error_id: int, body: ErrorCorrectIn,
                  db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    err = db.query(Error).filter(Error.id == error_id).first()
    if not err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    err.error_type = body.error_type
    err.teacher_note = body.teacher_note
    err.teacher_corrected = True
    db.commit()
    db.refresh(err)
    return _teacher_error_item(err, db)


@router.get("/stats/top-questions", summary="高频错题 TopN")
def stats_top_questions(n: int = Query(default=10, ge=1, le=50),
                        db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = top_error_questions(db, n)
    return {"n": n, "items": [TopQuestionItem(**it) for it in items]}


@router.get("/stats/knowledge-points", summary="知识点错误率排行")
def stats_knowledge_points(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = knowledge_point_ranking(db)
    return {"items": [KnowledgePointRankItem(**it) for it in items]}


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

def _teacher_assignment_out(a: Assignment, db: Session) -> TeacherAssignmentOut:
    questions = (
        db.query(Question).filter(Question.assignment_id == a.id)
        .order_by(Question.order_num, Question.id).all()
    )
    items = []
    for q in questions:
        count = db.query(Submission).filter(Submission.question_id == q.id).count()
        count += db.query(Essay).filter(Essay.question_id == q.id).count()
        items.append(TeacherAssignmentQuestionOut(
            id=q.id,
            type="math" if q.subject == "math" else "essay",
            prompt=q.stem,
            knowledge_point=q.knowledge_point,
            standard_answer=q.standard_answer,
            submission_count=count,
        ))
    return TeacherAssignmentOut(
        id=a.id, title=a.title, description=a.description,
        created_at=a.created_at, questions=items,
    )


@router.post("/assignments", response_model=TeacherAssignmentOut, summary="发布作业")
def create_assignment(body: TeacherAssignmentCreate,
                      db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """创建一份作业并落库，学生端立即可见。
    standard_steps 无独立存储列：落库时并入 standard_answer（参考答案优先）。"""
    assignment = Assignment(
        title=body.title, description=body.description, created_by=current.id,
    )
    db.add(assignment)
    db.flush()  # 拿到 assignment.id
    for i, q in enumerate(body.questions, start=1):
        standard_answer = q.reference_answer
        if not standard_answer and q.standard_steps:
            standard_answer = "\n".join(s.strip() for s in q.standard_steps if s.strip())
        db.add(Question(
            assignment_id=assignment.id,
            subject="math" if q.type == "math" else "english",
            knowledge_point=q.knowledge_point,
            stem=q.prompt,
            standard_answer=standard_answer,
            order_num=i,
        ))
    db.commit()
    db.refresh(assignment)
    return _teacher_assignment_out(assignment, db)


@router.get("/assignments", summary="已发布作业列表")
def list_teacher_assignments(db: Session = Depends(get_db),
                             current: User = Depends(require_teacher)):
    assignments = db.query(Assignment).order_by(Assignment.id).all()
    items = [_teacher_assignment_out(a, db) for a in assignments]
    return {"total": len(items), "items": items}
