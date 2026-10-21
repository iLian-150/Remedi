# Mock 认证：演示用，无密码。
# 学生按名册中的姓名+学号登录；教师按姓名+学科隔离；token 为 "mock-<user_id>"。
# ⚠️ 仅用于 MVP 演示/联调，生产环境必须替换为 JWT + 密码体系。
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import TeacherSubject, User

bearer_scheme = HTTPBearer(auto_error=False)

TOKEN_PREFIX = "mock-"


def create_token(user_id: int) -> str:
    return f"{TOKEN_PREFIX}{user_id}"


def get_or_create_user(
    db: Session,
    username: str,
    role: str,
    student_no: Optional[str] = None,
    subject: Optional[str] = None,
) -> User:
    """教师仍使用无密码演示登录；学生必须先由教师录入名册并用学号登录。"""
    if role == "student":
        normalized_no = (student_no or "").strip()
        if not normalized_no:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "学生登录需要学号。")
        user = db.query(User).filter(
            User.role == "student", User.student_no == normalized_no,
        ).first()
        if user is None or user.name != username:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "姓名与学号不匹配，请联系任课老师检查班级名册。")
        return user

    if role == "teacher" and subject:
        user = db.query(User).join(
            TeacherSubject, TeacherSubject.teacher_id == User.id,
        ).filter(
            User.name == username,
            User.role == "teacher",
            TeacherSubject.subject == subject,
        ).first()
        if user:
            return user
        # 老师已有同名账号但尚未绑定任教学科时，首次使用该账号并完成映射。
        legacy = db.query(User).filter(
            User.name == username,
            User.role == "teacher",
            ~db.query(TeacherSubject.teacher_id).filter(
                TeacherSubject.teacher_id == User.id,
            ).exists(),
        ).first()
        if legacy:
            return legacy

    user = User(name=username, student_no=None, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供 token，请先调用 /api/auth/login 登录")
    token = credentials.credentials
    if not token.startswith(TOKEN_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    try:
        user_id = int(token[len(TOKEN_PREFIX):])
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    return user


def require_student(current: User = Depends(get_current_user)) -> User:
    if current.role != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该接口仅学生可访问")
    return current


def require_teacher(current: User = Depends(get_current_user)) -> User:
    if current.role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该接口仅教师可访问")
    return current
