"""Student-owned assistant preferences exposed for the learning report."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_student
from ..database import get_db
from ..models import User
from ..api_schemas.student import StudentAssistantPreferencesOut
from ..services.assistant_preferences import student_assistant_preferences

router = APIRouter(prefix="/api/student", tags=["student"])


@router.get(
    "/assistant-preferences",
    response_model=StudentAssistantPreferencesOut,
    summary="读取我已保存的回答偏好",
)
def my_assistant_preferences(
    db: Session = Depends(get_db),
    current: User = Depends(require_student),
):
    return student_assistant_preferences(db, current.id)
