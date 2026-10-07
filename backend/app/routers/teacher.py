# /api/teacher/* 教师端
import os
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import require_teacher
from ..config import settings
from ..database import get_db
from ..models import Assignment, AssignmentExt, ChatMessage, Correction, Error, Essay, Notification, Question, Step, Submission, User, Workbook
from ..schemas import (
    AgentChatIn,
    AgentChatOut,
    AgentHistoryItem,
    ClassRepairRateOut,
    ErrorCorrectIn,
    KnowledgePointRankItem,
    PhotoTranscribeOut,
    ProfileOut,
    QuestionOut,
    RemindOut,
    StudentBrief,
    TeacherAssignmentCreate,
    TeacherAssignmentOut,
    TeacherAssignmentQuestionOut,
    TeacherErrorItem,
    TopQuestionItem,
    UserOut,
    WorkbookOut,
)
from ..services.diagnosis import present_error
from ..services.providers import get_provider
from ..services.stats import (
    assignment_ext_fields,
    class_repair_rate,
    knowledge_point_ranking,
    list_students,
    student_profile,
    top_error_questions,
)
from ..services.teacher_stats import students_not_fully_submitted

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

ERROR_TYPES = ("计算失误", "概念混淆", "审题遗漏", "无法解析")


def _teacher_error_item(err: Error, db: Session) -> TeacherErrorItem:
    sub = db.query(Submission).filter(Submission.id == err.submission_id).first()
    student = db.query(User).filter(User.id == sub.student_id).first() if sub else None
    question = db.query(Question).filter(Question.id == sub.question_id).first() if sub else None
    base = present_error(err, db)
    return TeacherErrorItem(
        id=base["id"],
        student=UserOut.model_validate(student),
        question=QuestionOut.model_validate(question),
        step_seq=base["step_seq"],
        step_text=base["step_text"],
        knowledge_point=base["knowledge_point"],
        error_type=base["error_type"],
        confidence=base["confidence"],
        is_stubborn=base["is_stubborn"],
        detail=base["detail"],
        teacher_corrected=base["teacher_corrected"],
        teacher_note=base["teacher_note"],
        created_at=base["created_at"],
    )


@router.get("/errors", summary="错误记录列表")
def list_errors(
    student_id: Optional[int] = Query(default=None),
    knowledge_point: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    stubborn_only: bool = Query(default=False),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current: User = Depends(require_teacher),
):
    query = db.query(Error).join(Submission, Error.submission_id == Submission.id)
    if student_id:
        query = query.filter(Submission.student_id == student_id)
    if knowledge_point:
        query = query.filter(Error.knowledge_point == knowledge_point)
    if error_type:
        if error_type not in ERROR_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"error_type 非法，应为 {ERROR_TYPES}")
        query = query.filter(Error.error_type == error_type)
    if stubborn_only:
        query = query.filter(Error.is_stubborn.is_(True))
    total = query.count()
    errs = query.order_by(Error.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_teacher_error_item(e, db) for e in errs]}


@router.post("/errors/{error_id}/correct", response_model=TeacherErrorItem, summary="教师一键纠错")
def correct_error(error_id: int, body: ErrorCorrectIn,
                  db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    err = db.query(Error).filter(Error.id == error_id).first()
    if not err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错误记录不存在")
    old_type = err.error_type
    err.error_type = body.error_type
    err.teacher_note = body.teacher_note
    err.teacher_corrected = True
    # v0.3.0：纠错成功后给被纠错的学生写一条站内提醒（主流程：AI 初批 → 老师干预 → 学生收到提醒去订正）
    sub = db.query(Submission).filter(Submission.id == err.submission_id).first()
    if sub is not None:
        question = db.query(Question).filter(Question.id == sub.question_id).first()
        assignment = (
            db.query(Assignment).filter(Assignment.id == question.assignment_id).first()
            if question else None
        )
        title = assignment.title if assignment else ""
        content = (
            f"{current.name}调整了你《{title}》的批改结果："
            f"错因由{old_type}改为{body.error_type}，点开看看老师的复核结果吧。"
        )
        db.add(Notification(
            user_id=sub.student_id,
            type="teacher_correction",
            content=content,
            related_submission_id=sub.id,
        ))
    db.commit()
    db.refresh(err)
    return _teacher_error_item(err, db)


@router.get("/stats/top-questions", summary="高频错题 TopN")
def stats_top_questions(n: int = Query(default=10, ge=1, le=50),
                        db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = top_error_questions(db, n)
    return {"n": n, "items": [TopQuestionItem(**it) for it in items]}


@router.get("/stats/knowledge-points", summary="知识点错误率排行")
def stats_knowledge_points(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = knowledge_point_ranking(db)
    return {"items": [KnowledgePointRankItem(**it) for it in items]}


@router.get("/stats/repair-rate", response_model=ClassRepairRateOut, summary="班级知识修复率（v0.4.0 新增）")
def stats_repair_rate(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """班级知识修复率 + 各知识点修复率：口径与学生学习报告四态一致
    （已修复 = 错题订正后通过二次验证）。"""
    return class_repair_rate(db)


@router.get("/students", summary="学生列表")
def students(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    items = list_students(db)
    return {"total": len(items), "items": [StudentBrief(**it) for it in items]}


@router.get("/students/{student_id}/profile", response_model=ProfileOut, summary="学生画像查询")
def student_profile_view(student_id: int, db: Session = Depends(get_db),
                         current: User = Depends(require_teacher)):
    st = db.query(User).filter(User.id == student_id, User.role == "student").first()
    if not st:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学生不存在")
    return student_profile(db, st)


# ---------- 发布作业（v0.2.0 新增） ----------

def _teacher_assignment_out(a: Assignment, db: Session) -> TeacherAssignmentOut:
    questions = (
        db.query(Question).filter(Question.assignment_id == a.id)
        .order_by(Question.order_num, Question.id).all()
    )
    items = []
    for q in questions:
        count = db.query(Submission).filter(Submission.question_id == q.id).count()
        count += db.query(Essay).filter(Essay.question_id == q.id).count()
        items.append(TeacherAssignmentQuestionOut(
            id=q.id,
            type="math" if q.subject == "math" else "essay",
            prompt=q.stem,
            knowledge_point=q.knowledge_point,
            standard_answer=q.standard_answer,
            submission_count=count,
        ))
    return TeacherAssignmentOut(
        id=a.id, title=a.title, description=a.description,
        created_at=a.created_at, questions=items,
        # v0.5.0：发布模式与线下作业信息
        **assignment_ext_fields(db, a.id),
    )


@router.post("/assignments", response_model=TeacherAssignmentOut, summary="发布作业")
def create_assignment(body: TeacherAssignmentCreate,
                      db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    """创建一份作业并落库，学生端立即可见。
    standard_steps 无独立存储列：落库时并入 standard_answer（参考答案优先）。
    v0.5.0：mode=offline 时把 mode/workbook_id/page_range/deadline 写进 assignment_ext；
    workbook_id 必须指向本人上传的练习册。"""
    workbook = None
    if body.mode == "offline" and body.workbook_id is not None:
        workbook = (
            db.query(Workbook)
            .filter(Workbook.id == body.workbook_id, Workbook.teacher_id == current.id)
            .first()
        )
        if not workbook:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选练习册不存在或不是你上传的")
    assignment = Assignment(
        title=body.title, description=body.description, created_by=current.id,
    )
    db.add(assignment)
    db.flush()  # 拿到 assignment.id
    for i, q in enumerate(body.questions, start=1):
        standard_answer = q.reference_answer
        if not standard_answer and q.standard_steps:
            standard_answer = "\n".join(s.strip() for s in q.standard_steps if s.strip())
        db.add(Question(
            assignment_id=assignment.id,
            subject="math" if q.type == "math" else "english",
            knowledge_point=q.knowledge_point,
            stem=q.prompt,
            standard_answer=standard_answer,
            order_num=i,
        ))
    if body.mode == "offline":
        db.add(AssignmentExt(
            assignment_id=assignment.id,
            mode="offline",
            workbook_id=workbook.id if workbook else None,
            page_range=(body.page_range or "").strip() or None,
            deadline=body.deadline,
        ))
    db.commit()
    db.refresh(assignment)
    return _teacher_assignment_out(assignment, db)


@router.get("/assignments", summary="已发布作业列表")
def list_teacher_assignments(db: Session = Depends(get_db),
                             current: User = Depends(require_teacher)):
    assignments = db.query(Assignment).order_by(Assignment.id).all()
    items = [_teacher_assignment_out(a, db) for a in assignments]
    return {"total": len(items), "items": items}


@router.delete("/assignments/{assignment_id}", summary="删除已发布作业")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_teacher)):
    """删除自己发布的一份作业（v0.3.0 新增）。事务内按外键依赖顺序级联删除：
    corrections → notifications（关联这些提交的）→ errors → steps → submissions
    → essays → questions → assignment，避免孤儿数据污染学生报告与班级统计。
    非本人发布或不存在统一返回 404（不泄露他人作业是否存在）。"""
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.created_by == current.id)
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    qids = [q.id for q in db.query(Question).filter(Question.assignment_id == assignment.id).all()]
    if qids:
        sub_ids = [
            s.id for s in db.query(Submission).filter(Submission.question_id.in_(qids)).all()
        ]
        if sub_ids:
            err_ids = [
                e.id for e in db.query(Error).filter(Error.submission_id.in_(sub_ids)).all()
            ]
            if err_ids:
                db.query(Correction).filter(Correction.error_id.in_(err_ids)) \
                    .delete(synchronize_session=False)
            db.query(Notification).filter(
                Notification.related_submission_id.in_(sub_ids)
            ).delete(synchronize_session=False)
            db.query(Error).filter(Error.submission_id.in_(sub_ids)) \
                .delete(synchronize_session=False)
            db.query(Step).filter(Step.submission_id.in_(sub_ids)) \
                .delete(synchronize_session=False)
            db.query(Submission).filter(Submission.id.in_(sub_ids)) \
                .delete(synchronize_session=False)
        db.query(Essay).filter(Essay.question_id.in_(qids)).delete(synchronize_session=False)
        db.query(Question).filter(Question.id.in_(qids)).delete(synchronize_session=False)
    # v0.5.0：作业扩展行（发布模式/练习册关联）一并删除
    db.query(AssignmentExt).filter(AssignmentExt.assignment_id == assignment.id) \
        .delete(synchronize_session=False)
    db.delete(assignment)
    db.commit()
    return {"deleted": True}


@router.post("/assignments/{assignment_id}/remind", response_model=RemindOut,
             summary="一键提醒未交学生（v0.5.0 新增）")
def remind_assignment(assignment_id: int, db: Session = Depends(get_db),
                      current: User = Depends(require_teacher)):
    """给「还没提交全部题目」的学生各写一条站内提醒（便利贴通知），
    只统计/只提醒未全交的学生；全部完成的学生不会收到。仅限本人发布的作业。"""
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == assignment_id, Assignment.created_by == current.id)
        .first()
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "作业不存在")
    targets = students_not_fully_submitted(db, assignment)
    for st in targets:
        db.add(Notification(
            user_id=st.id,
            type="teacher_reminder",
            content=f"{current.name}提醒你：《{assignment.title}》还没有完成，记得及时提交哦",
            related_submission_id=None,
        ))
    db.commit()
    return {"reminded_count": len(targets)}


# ---------- 练习册知识库（v0.5.0 新增） ----------

_WORKBOOK_MAX_BYTES = 30 * 1024 * 1024
_WORKBOOK_SUBDIR = "workbooks"


def _workbook_out(w: Workbook) -> WorkbookOut:
    return WorkbookOut(
        id=w.id,
        title=w.title,
        file_url=f"/api/uploads/{w.file_path}",
        created_at=w.created_at,
    )


@router.post("/workbooks", response_model=WorkbookOut, summary="上传练习册 PDF")
async def upload_workbook(file: UploadFile = File(...),
                          db: Session = Depends(get_db),
                          current: User = Depends(require_teacher)):
    """上传整本练习册 PDF 存入知识库（UPLOAD_DIR/workbooks/），发布线下作业时可直接选用。
    仅 PDF、≤30MB；标题默认取文件名（去扩展名），文件只存盘、元信息落 workbooks 表。"""
    filename = (file.filename or "").strip()
    is_pdf = file.content_type == "application/pdf" or filename.lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只支持上传 PDF 文件")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件内容为空，请重新上传")
    if len(data) > _WORKBOOK_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF 大小不能超过 30MB")
    target_dir = os.path.join(settings.UPLOAD_DIR, _WORKBOOK_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)
    stored_name = "{}_{}.pdf".format(
        datetime.now().strftime("%Y%m%d%H%M%S"), secrets.token_hex(4)
    )
    with open(os.path.join(target_dir, stored_name), "wb") as f:
        f.write(data)
    base = os.path.splitext(os.path.basename(filename))[0].strip()
    w = Workbook(
        teacher_id=current.id,
        title=base or "未命名练习册",
        file_path=f"{_WORKBOOK_SUBDIR}/{stored_name}",
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _workbook_out(w)


@router.get("/workbooks", summary="我的练习册知识库")
def list_workbooks(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    rows = (
        db.query(Workbook)
        .filter(Workbook.teacher_id == current.id)
        .order_by(Workbook.created_at.desc(), Workbook.id.desc())
        .all()
    )
    return {"total": len(rows), "items": [_workbook_out(w) for w in rows]}


@router.delete("/workbooks/{workbook_id}", summary="删除练习册")
def delete_workbook(workbook_id: int, db: Session = Depends(get_db),
                    current: User = Depends(require_teacher)):
    """删除本人上传的一本练习册（连同 PDF 文件）。已被线下作业引用的也可删除：
    对应 assignment_ext.workbook_id 置空，作业本身与其余信息保留。非本人/不存在统一 404。"""
    w = (
        db.query(Workbook)
        .filter(Workbook.id == workbook_id, Workbook.teacher_id == current.id)
        .first()
    )
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "练习册不存在")
    db.query(AssignmentExt).filter(AssignmentExt.workbook_id == w.id) \
        .update({AssignmentExt.workbook_id: None}, synchronize_session=False)
    try:
        os.remove(os.path.join(settings.UPLOAD_DIR, w.file_path))
    except OSError:
        pass  # 文件已不在磁盘上时不阻塞删除元信息
    db.delete(w)
    db.commit()
    return {"deleted": True}


# ---------- 教师 AI 助手（v0.5.0 新增，LangGraph；与学生端同图结构、工具换班级数据） ----------

_AGENT_MSG_MAX = 2000
_AGENT_HISTORY_WINDOW = 20
_AGENT_HISTORY_RETURN = 50


@router.post("/agent/chat", response_model=AgentChatOut, summary="与班级数据助理对话")
def teacher_agent_chat(body: AgentChatIn, db: Session = Depends(get_db),
                       current: User = Depends(require_teacher)):
    """教师端自由对话：取最近 20 条历史组上下文 → 跑教师 Agent 图（或规则兜底）
    → 两条消息落 chat_messages（user_id 区分身份）→ 返回回复。LLM 异常已在 Agent 层降级。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from ..agent.teacher_graph import teacher_agent_reply

    text = body.message.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "消息不能为空")
    if len(text) > _AGENT_MSG_MAX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "消息有点长，单条最多 2000 字，请分开发送")

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(_AGENT_HISTORY_WINDOW)
        .all()
    )
    history = [
        HumanMessage(content=r.content) if r.role == "user" else AIMessage(content=r.content)
        for r in reversed(rows)
    ]
    reply = teacher_agent_reply(db, current, history, text)

    db.add(ChatMessage(user_id=current.id, role="user", content=text))
    db.add(ChatMessage(user_id=current.id, role="assistant", content=reply))
    db.commit()
    return {"reply": reply}


@router.get("/agent/history", response_model=List[AgentHistoryItem], summary="教师对话历史")
def teacher_agent_history(db: Session = Depends(get_db), current: User = Depends(require_teacher)):
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(_AGENT_HISTORY_RETURN)
        .all()
    )
    return [
        AgentHistoryItem(role=r.role, content=r.content, created_at=r.created_at)
        for r in reversed(rows)
    ]


@router.post("/agent/new-session", summary="开始新对话（清空教师对话记录，v0.5.0 新增）")
def teacher_agent_new_session(db: Session = Depends(get_db),
                              current: User = Depends(require_teacher)):
    cleared = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"cleared_count": cleared}


# ---------- 拍照识别题目（v0.2.1 新增） ----------

_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp"}
_PHOTO_MAX_BYTES = 10 * 1024 * 1024


@router.post("/photo-recognize", response_model=PhotoTranscribeOut, summary="拍照识别题目")
async def photo_recognize(file: UploadFile = File(...),
                          current: User = Depends(require_teacher)):
    """上传题目照片 → Provider 视觉转写 → 返回 {question_text, steps}（含图片回读信息）。
    规则与学生端 photo-transcribe 一致（jpg/png/webp、≤10MB、存同一 UPLOAD_DIR）；
    前端把 question_text 填入题干、steps 填入标准步骤，教师检查修改后再发布。
    注意：v1 直接复用学生作答转写能力（transcribe_image），未针对题目照片单独调 prompt。"""
    if file.content_type not in _PHOTO_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 格式的图片")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片内容为空，请重新上传")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片大小不能超过 10MB")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = "{}_{}{}".format(
        datetime.now().strftime("%Y%m%d%H%M%S"),
        secrets.token_hex(4),
        _PHOTO_TYPES[file.content_type],
    )
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(data)
    result = get_provider().transcribe_image(data, file.content_type)
    return {
        "image_id": filename,
        "image_url": f"/api/uploads/{filename}",
        "question_text": result.get("question_text", ""),
        "steps": result.get("steps", []),
    }
