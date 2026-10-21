# /api/auth/*
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import create_token, get_current_user, get_or_create_user
from ..database import get_db
from ..models import ClassroomMember, TeacherSubject, User
from ..schemas import LoginIn, LoginOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut, summary="Mock 登录")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """教师无密码演示登录；学生使用教师名册里的姓名+学号登录。"""
    username = body.username.strip()
    if body.role == "teacher" and not body.subject:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "教师登录需要选择任教学科。")
    user = get_or_create_user(
        db, username, body.role, body.student_no, body.subject,
    )
    if body.role == "teacher":
        mapping = db.query(TeacherSubject).filter_by(
            teacher_id=user.id, subject=body.subject,
        ).first()
        if mapping is None:
            db.add(TeacherSubject(teacher_id=user.id, subject=body.subject))
            db.commit()
    elif not db.query(ClassroomMember.classroom_id).filter_by(
        student_id=user.id,
    ).first():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该学生尚未加入班级名册，请联系任课老师。")
    return LoginOut(
        token=create_token(user.id), user=UserOut.model_validate(user),
        active_subject=body.subject if body.role == "teacher" else None,
    )


@router.get("/me", response_model=UserOut, summary="当前登录用户")
def me(current: User = Depends(get_current_user)):
    return UserOut.model_validate(current)
