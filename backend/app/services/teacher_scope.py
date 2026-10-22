"""Shared data scope for a teacher's assigned subjects and classrooms."""

from sqlalchemy import and_, or_

from ..models import (
    Assignment,
    AssignmentClass,
    ClassroomMember,
    ClassroomTeacherSubject,
    Essay,
    Question,
    Submission,
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


def teacher_assignment_student_ids(db, teacher: User, assignment_id: int):
    """Return recipients the teacher may include in this assignment's roster.

    Non-owners need a matching classroom+subject assignment for each recipient
    class. Owners may manage all explicit recipients. ``None`` preserves the
    legacy all-students behavior for assignments without recipient rows.
    """
    recipient_class_ids = db.query(AssignmentClass.classroom_id).filter(
        AssignmentClass.assignment_id == assignment_id,
    )
    if not recipient_class_ids.first():
        return None

    subjects = db.query(TeacherSubject.subject).filter(
        TeacherSubject.teacher_id == teacher.id,
    )
    owns_assignment = db.query(Question.id).join(
        Assignment, Assignment.id == Question.assignment_id,
    ).filter(
        Assignment.id == assignment_id,
        Assignment.created_by == teacher.id,
        Question.subject.in_(subjects),
    ).first()
    if owns_assignment:
        return [row[0] for row in db.query(ClassroomMember.student_id).join(
            AssignmentClass,
            AssignmentClass.classroom_id == ClassroomMember.classroom_id,
        ).filter(
            AssignmentClass.assignment_id == assignment_id,
        ).distinct().all()]

    return [row[0] for row in db.query(ClassroomMember.student_id).join(
        AssignmentClass,
        AssignmentClass.classroom_id == ClassroomMember.classroom_id,
    ).join(
        ClassroomTeacherSubject,
        ClassroomTeacherSubject.classroom_id == AssignmentClass.classroom_id,
    ).join(
        Question,
        and_(
            Question.assignment_id == AssignmentClass.assignment_id,
            Question.subject == ClassroomTeacherSubject.subject,
        ),
    ).filter(
        AssignmentClass.assignment_id == assignment_id,
        ClassroomTeacherSubject.teacher_id == teacher.id,
    ).distinct().all()]


def _teacher_activity_ids(db, teacher: User, activity_model):
    """Return activity rows owned by the teacher or from an assigned class+subject.

    Assignments may be shared across classes, so the assignment itself is not a
    sufficient scope for individual submissions or essays.
    """
    subjects = db.query(TeacherSubject.subject).filter(
        TeacherSubject.teacher_id == teacher.id,
    )
    owned = db.query(activity_model.id).join(
        Question, Question.id == activity_model.question_id,
    ).join(
        Assignment, Assignment.id == Question.assignment_id,
    ).filter(
        Assignment.created_by == teacher.id,
        Question.subject.in_(subjects),
    )
    assigned = db.query(activity_model.id).join(
        Question, Question.id == activity_model.question_id,
    ).join(
        AssignmentClass, AssignmentClass.assignment_id == Question.assignment_id,
    ).join(
        ClassroomTeacherSubject,
        and_(
            ClassroomTeacherSubject.classroom_id == AssignmentClass.classroom_id,
            ClassroomTeacherSubject.subject == Question.subject,
        ),
    ).join(
        ClassroomMember,
        and_(
            ClassroomMember.classroom_id == AssignmentClass.classroom_id,
            ClassroomMember.student_id == activity_model.student_id,
        ),
    ).filter(ClassroomTeacherSubject.teacher_id == teacher.id)
    return db.query(activity_model.id).filter(
        or_(activity_model.id.in_(owned), activity_model.id.in_(assigned)),
    ).distinct()


def teacher_submission_ids(db, teacher: User):
    return _teacher_activity_ids(db, teacher, Submission)


def teacher_essay_ids(db, teacher: User):
    return _teacher_activity_ids(db, teacher, Essay)
