"""Shared data scope for a teacher's assigned subjects and classrooms."""

from sqlalchemy import and_, or_

from ..models import (
    Assignment,
    AssignmentClass,
    ClassroomMember,
    ClassroomTeacherSubject,
    Question,
    TeacherSubject,
    User,
)


def teacher_assignment_ids(db, teacher: User):
    """Return assignments owned by this teacher in their subjects or assigned to their classes."""
    subjects = db.query(TeacherSubject.subject).filter(
        TeacherSubject.teacher_id == teacher.id,
    )
    owned = db.query(Question.assignment_id).join(
        Assignment, Assignment.id == Question.assignment_id,
    ).filter(
        Assignment.created_by == teacher.id,
        Question.subject.in_(subjects),
    )
    assigned = db.query(AssignmentClass.assignment_id).join(
        ClassroomTeacherSubject,
        ClassroomTeacherSubject.classroom_id == AssignmentClass.classroom_id,
    ).join(
        Question,
        and_(
            Question.assignment_id == AssignmentClass.assignment_id,
            Question.subject == ClassroomTeacherSubject.subject,
        ),
    ).filter(ClassroomTeacherSubject.teacher_id == teacher.id)
    return db.query(Assignment.id).filter(
        or_(Assignment.id.in_(owned), Assignment.id.in_(assigned)),
    ).distinct()


def teacher_student_ids(db, teacher: User):
    """Return students in classrooms for which this teacher has a subject assignment."""
    return db.query(ClassroomMember.student_id).join(
        ClassroomTeacherSubject,
        ClassroomTeacherSubject.classroom_id == ClassroomMember.classroom_id,
    ).filter(ClassroomTeacherSubject.teacher_id == teacher.id).distinct()
