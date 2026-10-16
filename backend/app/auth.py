# Mock 认证：演示用，无密码。
# 登录时按 username+role 查找用户，不存在则自动创建；token 格式为 "mock-<user_id>"。
# ⚠️ 仅用于 MVP 演示/联调，生产环境必须替换为 JWT + 密码体系。
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

bearer_scheme = HTTPBearer(auto_error=False)

TOKEN_PREFIX = "mock-"
_FIRST_STUDENT_NUMBER = 2026001
_STUDENT_CREATE_RETRIES = 100


def create_token(user_id: int) -> str:
    return f"{TOKEN_PREFIX}{user_id}"


def _next_student_no(db: Session) -> str:
    """Pick the first free number at or above the current sequential position."""
    next_number = _FIRST_STUDENT_NUMBER + db.query(User.id).filter(
        User.role == "student",
    ).count()
    while True:
        student_no = f"S{next_number}"
        occupied = db.query(User.id).filter(User.student_no == student_no).first()
        if occupied is None:
            return student_no
        next_number += 1


def get_or_create_user(db: Session, username: str, role: str) -> User:
    user = db.query(User).filter(User.name == username, User.role == role).first()
    if user:
        return user

    if role != "student":
        user = User(name=username, student_no=None, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    # 学号按现有顺序生成；删除用户留下的空洞会被跳过，避免唯一约束冲突。
    for _ in range(_STUDENT_CREATE_RETRIES):
        student_no = _next_student_no(db)
        user = User(name=username, student_no=student_no, role=role)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # 并发请求可能已创建同名账号；如果只是学号被抢占，则重算后再试。
            existing = db.query(User).filter(
                User.name == username, User.role == role,
            ).first()
            if existing:
                return existing
            occupied = db.query(User.id).filter(
                User.student_no == student_no,
            ).first()
            if occupied:
                continue
            raise
        db.refresh(user)
        return user

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "学生账号创建繁忙，请稍后重试。",
    )


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
