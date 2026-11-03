"""在保留题目编号和学生数据的前提下编辑已发布作业。"""
import hashlib
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_teacher
from ..database import get_db
from ..models import (
    Assignment, AssignmentClass, AssignmentExt, AssignmentGradingJob, AssignmentScoring,
    AssignmentSetting, Classroom, ClassroomTeacherSubject, DiagramJob, Essay,
    Question, QuestionGroup, QuestionGroupMember, QuestionWeight, Submission,
    TeacherSubject, User,
)
from ..services import deferral as deferral_svc, diagram_jobs, scoring

router = APIRouter(prefix="/api/teacher/assignments", tags=["teacher"])


class EditQuestion(BaseModel):
    id: int
    prompt: str = Field(min_length=1, max_length=2000)
    knowledge_point: str = Field(default="", max_length=64)
    standard_answer: Optional[str] = Field(default=None, max_length=60000)
    weight_pct: float = Field(ge=0, le=100)


class EditGroup(BaseModel):
    id: int
    stem: str = Field(min_length=1, max_length=4000)


class EditAssignment(BaseModel):
    revision: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2000)
    total_score: float = Field(gt=0, le=10000)
    deadline: Optional[datetime] = None
    page_range: Optional[str] = Field(default=None, max_length=64)
    allow_revision: bool = False
    class_ids: List[int] = Field(default_factory=list, max_length=100)
    questions: List[EditQuestion] = Field(min_length=1, max_length=50)
    groups: List[EditGroup] = Field(default_factory=list, max_length=20)


def _owner_assignment(db: Session, current: User, assignment_id: int):
    assignment = db.query(Assignment).filter_by(id=assignment_id, created_by=current.id).first()
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在或你没有编辑权限。")
    subjects = {row[0] for row in db.query(TeacherSubject.subject).filter_by(teacher_id=current.id).all()}
    questions = db.query(Question).filter_by(assignment_id=assignment_id).order_by(Question.order_num, Question.id).all()
    if not questions or any(question.subject not in subjects for question in questions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前账号没有该作业全部学科的编辑权限。")
    return assignment, questions


def _has_activity(db: Session, assignment_id: int) -> bool:
    if db.query(AssignmentGradingJob.id).filter_by(assignment_id=assignment_id).first():
        return True
    qids = db.query(Question.id).filter_by(assignment_id=assignment_id)
    return bool(db.query(Submission.id).filter(Submission.question_id.in_(qids)).first()
                or db.query(Essay.id).filter(Essay.question_id.in_(qids)).first())


def _edit_state(db: Session, assignment, questions):
    groups = db.query(QuestionGroup).filter_by(assignment_id=assignment.id).order_by(QuestionGroup.order_num, QuestionGroup.id).all()
    qids = [q.id for q in questions]
    memberships = dict(db.query(QuestionGroupMember.question_id, QuestionGroupMember.group_id).filter(
        QuestionGroupMember.question_id.in_(qids)).all())
    weights = dict(db.query(QuestionWeight.question_id, QuestionWeight.weight_pct).filter(
        QuestionWeight.question_id.in_(qids)).all())
    score = db.get(AssignmentScoring, assignment.id)
    extension = db.get(AssignmentExt, assignment.id)
    setting = db.get(AssignmentSetting, assignment.id)
    class_ids = sorted(row[0] for row in db.query(AssignmentClass.classroom_id).filter_by(assignment_id=assignment.id).all())
    data = {
        "id": assignment.id, "title": assignment.title, "description": assignment.description,
        "total_score": float(score.total_score) if score else 100.0,
        "deadline": extension.deadline.isoformat() if extension and extension.deadline else None,
        "mode": extension.mode if extension else "online",
        "page_range": extension.page_range if extension else None,
        "allow_revision": bool(setting.allow_revision) if setting else False,
        "class_ids": class_ids,
        "questions": [{"id": q.id, "subject": q.subject, "prompt": q.stem,
                       "knowledge_point": q.knowledge_point, "standard_answer": q.standard_answer,
                       "group_id": memberships.get(q.id),
                       "weight_pct": float(weights[q.id]) if q.id in weights else 100.0 / len(questions)} for q in questions],
        "groups": [{"id": g.id, "stem": g.stem} for g in groups],
    }
    data["revision"] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    data["content_locked"] = _has_activity(db, assignment.id)
    subjects = {q.subject for q in questions}
    pairs = db.query(ClassroomTeacherSubject.classroom_id, ClassroomTeacherSubject.subject).filter(
        ClassroomTeacherSubject.teacher_id == assignment.created_by,
        ClassroomTeacherSubject.subject.in_(subjects),
    ).all()
    subjects_by_class = {}
    for class_id, subject in pairs:
        subjects_by_class.setdefault(class_id, set()).add(subject)
    class_options = {class_id for class_id, assigned in subjects_by_class.items() if subjects <= assigned}
    class_options.update(class_ids)
    data["class_options"] = [{"id": room.id, "name": room.name} for room in db.query(Classroom).filter(
        Classroom.id.in_(class_options)).order_by(Classroom.name, Classroom.id).all()]
    return data


@router.get("/{assignment_id}/edit", summary="读取可编辑的作业")
def get_assignment_edit(assignment_id: int, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    assignment, questions = _owner_assignment(db, current, assignment_id)
    return _edit_state(db, assignment, questions)


@router.put("/{assignment_id}", summary="保存作业编辑")
def update_assignment(assignment_id: int, body: EditAssignment, db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    assignment, questions = _owner_assignment(db, current, assignment_id)
    # 与学生提交时使用同一题目锁；SQLite 上该锁覆盖整个写事务。
    deferral_svc._lock_question_for_submission(db, questions[0])
    db.expire_all()
    assignment, questions = _owner_assignment(db, current, assignment_id)
    before = _edit_state(db, assignment, questions)
    if before["revision"] != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "作业已被修改，请重新加载后再编辑。")
    qdata = {q.id: q for q in body.questions}
    gdata = {g.id: g for g in body.groups}
    if len(qdata) != len(body.questions) or set(qdata) != {q.id for q in questions} or len(gdata) != len(body.groups) or set(gdata) != {g["id"] for g in before["groups"]}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "题目列表已变化，请重新加载。")
    if not body.title.strip() or any(not q.prompt.strip() for q in body.questions) or any(not g.stem.strip() for g in body.groups):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "作业标题和题干不能为空。")
    deadline = deferral_svc.normalize_deadline(body.deadline)
    old_deadline = datetime.fromisoformat(before["deadline"]) if before["deadline"] else None
    deadline_changed = deadline != old_deadline
    class_ids = sorted(set(body.class_ids))
    if len(class_ids) != len(body.class_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "接收班级不能重复。")
    old_q = {q["id"]: q for q in before["questions"]}
    old_g = {g["id"]: g for g in before["groups"]}
    changed_groups = {gid for gid, item in gdata.items() if item.stem.strip() != old_g[gid]["stem"]}
    page_range = (body.page_range or "").strip() or None
    if before["mode"] != "offline" and page_range is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "线上作业不能设置练习册范围。")
    class_changed = class_ids != before["class_ids"]
    content_changed = (abs(body.total_score - before["total_score"]) > 1e-8 or bool(changed_groups)
                       or deadline_changed or page_range != before["page_range"]
                       or body.allow_revision != before["allow_revision"] or class_changed)
    for q in questions:
        item, old = qdata[q.id], old_q[q.id]
        if item.prompt.strip() != q.stem and old["group_id"] is not None:
            changed_groups.add(old["group_id"])
        if (item.prompt.strip() != q.stem or item.knowledge_point.strip() != q.knowledge_point
                or (item.standard_answer or "").strip() != (q.standard_answer or "").strip()
                or abs(item.weight_pct - old["weight_pct"]) > 0.005):
            content_changed = True
    if before["content_locked"] and content_changed:
        raise HTTPException(status.HTTP_409_CONFLICT, "已有学生作答，不能修改题目、分值、班级或提交设置；仍可修改名称和说明。")
    if content_changed and abs(sum(q.weight_pct for q in body.questions) - 100) > 0.5:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "题目分值占比合计应为 100%。")
    if deadline_changed and deadline is not None and deadline <= deferral_svc.deadline_now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "截止时间必须晚于当前时间。")
    if class_changed:
        if not class_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请至少选择一个接收班级。")
        subjects = {q.subject for q in questions}
        pairs = set(db.query(ClassroomTeacherSubject.classroom_id, ClassroomTeacherSubject.subject).filter(
            ClassroomTeacherSubject.teacher_id == current.id,
            ClassroomTeacherSubject.classroom_id.in_(class_ids),
            ClassroomTeacherSubject.subject.in_(subjects),
        ).all())
        if any((class_id, subject) not in pairs for class_id in class_ids for subject in subjects):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选班级没有关联当前作业的全部学科。")
    assignment.title = body.title.strip()
    assignment.description = (body.description or "").strip() or None
    if content_changed:
        extension = db.get(AssignmentExt, assignment_id)
        if extension is None and (deadline is not None or page_range is not None):
            extension = AssignmentExt(assignment_id=assignment_id, mode=before["mode"])
            db.add(extension)
        if extension is not None:
            extension.deadline = deadline
            extension.page_range = page_range
        setting = db.get(AssignmentSetting, assignment_id)
        if setting is None and body.allow_revision:
            db.add(AssignmentSetting(assignment_id=assignment_id, allow_revision=True))
        elif setting is not None:
            setting.allow_revision = body.allow_revision
        if class_changed:
            db.query(AssignmentClass).filter_by(assignment_id=assignment_id).delete(synchronize_session=False)
            db.add_all(AssignmentClass(assignment_id=assignment_id, classroom_id=class_id) for class_id in class_ids)
        groups = {g.id: g for g in db.query(QuestionGroup).filter_by(assignment_id=assignment_id).all()}
        for gid, item in gdata.items():
            groups[gid].stem = item.stem.strip()
        for q in questions:
            item = qdata[q.id]
            q.stem, q.knowledge_point = item.prompt.strip(), item.knowledge_point.strip()
            q.standard_answer = (item.standard_answer or "").strip() or None
        scoring.set_assignment_scoring(db, assignment_id, body.total_score, [(q.id, qdata[q.id].weight_pct) for q in questions])
        # 旧图与题目快照不一致时废弃旧任务，并为已有图形自动重新生成。
        for gid in changed_groups:
            group = groups[gid]
            had_figure = bool(group.diagram_json) or bool(db.query(DiagramJob.id).filter_by(group_id=gid).first())
            # 保留旧任务编号并取消其运行结果，避免正在执行的旧任务与新任务复用 ID。
            db.query(DiagramJob).filter_by(group_id=gid).update(
                {DiagramJob.group_id: None, DiagramJob.status: "cancelled"}, synchronize_session=False)
            group.diagram_json = None
            members = [q for q in questions if old_q[q.id]["group_id"] == gid]
            if had_figure and members:
                text = "\n".join([group.stem.strip(), *[q.stem.strip() for q in members]])
                db.add(DiagramJob(teacher_id=current.id, group_id=gid, subject=members[0].subject,
                                  question_text=text[:12000], status="queued"))
    db.commit()
    if changed_groups:
        diagram_jobs.enqueue()
    return {"updated": True}
