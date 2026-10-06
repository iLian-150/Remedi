# /api/auth/*
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import create_token, get_current_user, get_or_create_user
from ..database import get_db
from ..models import User
from ..schemas import LoginIn, LoginOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut, summary="Mock 登录")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """传用户名+角色即登录；用户不存在则自动创建（演示用，无密码）。"""
    user = get_or_create_user(db, body.username.strip(), body.role)
    return LoginOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="当前登录用户")
def me(current: User = Depends(get_current_user)):
    return UserOut.model_validate(current)
