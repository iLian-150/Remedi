"""教师端 AI 图形生成接口。"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DiagramJob, QuestionGroup, Assignment
from ..services import diagram_jobs

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


def _job_out(job):
    return {"id": job.id, "status": job.status, "figure": json.loads(job.figure_json) if job.figure_json else None, "message": job.message, "group_id": job.group_id}


@router.post("/jobs", summary="开始生成图形")
def start_figure_job(body: FigureGenerateIn, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    job = DiagramJob(teacher_id=current.id, subject=body.subject, question_text=body.question_text, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    diagram_jobs.enqueue()
    return _job_out(job)


@router.get("/jobs", summary="查询已发布作业的图形任务")
def list_figure_jobs(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    jobs = db.query(DiagramJob, QuestionGroup.assignment_id).join(QuestionGroup, DiagramJob.group_id == QuestionGroup.id).join(Assignment, Assignment.id == QuestionGroup.assignment_id).filter(DiagramJob.teacher_id == current.id, Assignment.created_by == current.id).all()
    return [{**_job_out(job), "assignment_id": assignment_id} for job, assignment_id in jobs]


@router.get("/jobs/{job_id}", summary="查询图形生成进度")
def get_figure_job(job_id: int, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    job = db.query(DiagramJob).filter_by(id=job_id, teacher_id=current.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图形任务不存在")
    return _job_out(job)


@router.post("/jobs/{job_id}/retry", summary="重试图形生成")
def retry_figure_job(job_id: int, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    job = db.query(DiagramJob).filter_by(id=job_id, teacher_id=current.id, status="failed").first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "可重试的图形任务不存在")
    job.status, job.message = "queued", ""
    db.commit()
    diagram_jobs.enqueue()
    return _job_out(job)
