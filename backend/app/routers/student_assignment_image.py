"""学生本人查看私有作业暂存图片。"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import require_student
from ..database import get_db
from ..models import AssignmentGradingAnswer, AssignmentGradingJob, User
from ..services.assignment_grading import _draft_image_path
from .student import _student_accessible_question

router = APIRouter(prefix="/api/student/assignments", tags=["student"])


@router.get("/{assignment_id}/answers/{question_id}/image", summary="查看本人的作答照片")
def staged_image(assignment_id: int, question_id: int, db: Session = Depends(get_db), current: User = Depends(require_student)):
    question = _student_accessible_question(db, current, question_id)
    if question.assignment_id != assignment_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答图片不存在。")
    job = db.query(AssignmentGradingJob).filter_by(
        assignment_id=assignment_id, student_id=current.id,
    ).order_by(AssignmentGradingJob.id.desc()).first()
    if not job or job.status == "completed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答图片不存在。")
    answer = db.query(AssignmentGradingAnswer).filter_by(job_id=job.id, question_id=question_id).first()
    if not answer or not answer.image_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答图片不存在。")
    try:
        target = _draft_image_path(answer.image_path)
    except (ValueError, OSError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答图片不存在。") from None
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(target.suffix.lower())
    if not mime or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作答图片不存在。")
    return FileResponse(target, media_type=mime, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
