"""教师端 AI 图形生成接口。"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..api_schemas.diagram import FigureGenerateIn, FigureGenerateOut
from ..auth import require_teacher
from ..models import User
from ..services.diagram_generation import generate_figure

router = APIRouter(prefix="/api/teacher/diagrams", tags=["teacher"])


@router.post("/generate", response_model=FigureGenerateOut, summary="按题目内容生成教学图形")
def create_figure(body: FigureGenerateIn, _current: User = Depends(require_teacher)):
    try:
        figure, message = generate_figure(body.subject, body.question_text)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    return FigureGenerateOut(figure=figure, message=message)
