# 提交规则与延迟批改（v0.13.1）：
# - 默认每道题只能提交一次（教师在发布时未勾选「允许修改」时）。
# - 勾选 allow_revision 的作业：截止前学生可反复修改，每次修改落一份
#   status="deferred" 的提交（只存原始步骤，不诊断、不建审核行）；
#   截止时间到后由 grade_due() 把每道题的最后一次延迟提交统一批改
#   （复用原提交行走 diagnose_submission，再进教师审核队列），
#   被覆盖的旧延迟提交标 superseded 不再处理。
# - 没设截止时间的 allow_revision 作业不延迟（无截止可等），按立即批改 +
#   允许覆盖走（lock 检查放行、旧提交保留为历史，最新一份生效）。
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import AssignmentExt, AssignmentSetting, Question, Step, Submission, User
from .diagnosis import diagnose_submission
from . import reviews as review_svc

DEFERRED = "deferred"
SUPERSEDED = "superseded"


def allow_revision(db: Session, assignment_id: int) -> bool:
    setting = (
        db.query(AssignmentSetting)
        .filter(AssignmentSetting.assignment_id == assignment_id)
        .first()
    )
    return bool(setting.allow_revision) if setting else False


def assignment_deadline(db: Session, assignment_id: int) -> Optional[datetime]:
    ext = db.query(AssignmentExt).filter(AssignmentExt.assignment_id == assignment_id).first()
    return ext.deadline if ext else None


def is_deferred_mode(db: Session, assignment_id: int) -> bool:
    """当前是否处于「只收不改（批）」窗口：开了允许修改、设了截止、且还没到期。"""
    if not allow_revision(db, assignment_id):
        return False
    deadline = assignment_deadline(db, assignment_id)
    return bool(deadline and datetime.now() < deadline)


def latest_submission(db: Session, student_id: int, question_id: int) -> Optional[Submission]:
    return (
        db.query(Submission)
        .filter(Submission.student_id == student_id, Submission.question_id == question_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .first()
    )


def assert_can_submit(db: Session, student: User, question: Question) -> None:
    """提交锁定：已有生效提交且作业不允许（或已过可修改窗口）→ 拒绝再交。

    放行情形：从未提交过；或作业开启允许修改且最新提交还是延迟态
    （截止前的修改）；或开启允许修改但没设截止（立即批改口径下继续放行）。"""
    latest = latest_submission(db, student.id, question.id)
    if latest is None:
        return
    if latest.status == DEFERRED:
        return  # 截止前修改：新的延迟提交会成为最新一份
    if allow_revision(db, question.assignment_id) and assignment_deadline(db, question.assignment_id) is None:
        return  # 无截止的允许修改作业：立即批改口径，继续放行
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "这道题已经提交过了，每道题只能提交一次。",
    )


def create_deferred(db: Session, student: User, question: Question, step_texts: List[str]) -> Submission:
    """落一份延迟提交：只存原始步骤（seq 从 1 开始，status=deferred 占位），不诊断。"""
    submission = Submission(student_id=student.id, question_id=question.id, status=DEFERRED)
    db.add(submission)
    db.flush()
    for i, raw in enumerate(step_texts, start=1):
        db.add(Step(submission_id=submission.id, seq=i, text=raw, status=DEFERRED))
    db.commit()
    db.refresh(submission)
    return submission


def deferred_out(submission: Submission) -> dict:
    """延迟提交的 DiagnosisOut 形态：结论为空，status/review_status 均为 deferred。"""
    return {
        "submission_id": submission.id,
        "question_id": submission.question_id,
        "status": DEFERRED,
        "first_error_seq": None,
        "steps": [],
        "errors": [],
        "follow_up_question": None,
        "review_status": DEFERRED,
        "score": None,
    }


def grade_due(db: Session) -> int:
    """到期统一批改：扫所有 allow_revision 作业，截止已过的，把每道题
    每个学生的最后一次延迟提交批改掉；返回本次批改的提交数。
    幂等：已批改的提交不再是 deferred，不会重复处理。"""
    now = datetime.now()
    settings = db.query(AssignmentSetting).filter(AssignmentSetting.allow_revision.is_(True)).all()
    graded = 0
    for setting in settings:
        deadline = assignment_deadline(db, setting.assignment_id)
        if not deadline or now < deadline:
            continue
        qids = [
            q.id for q in db.query(Question)
            .filter(Question.assignment_id == setting.assignment_id).all()
        ]
        if not qids:
            continue
        deferred = (
            db.query(Submission)
            .filter(Submission.question_id.in_(qids), Submission.status == DEFERRED)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .all()
        )
        seen_pairs = set()
        for sub in deferred:
            pair = (sub.student_id, sub.question_id)
            if pair in seen_pairs:
                sub.status = SUPERSEDED  # 同题更早的修改版本，不批改
                continue
            seen_pairs.add(pair)
            student = db.query(User).filter(User.id == sub.student_id).first()
            question = db.query(Question).filter(Question.id == sub.question_id).first()
            if student is None or question is None:
                sub.status = SUPERSEDED
                continue
            step_texts = [
                s.text for s in (
                    db.query(Step)
                    .filter(Step.submission_id == sub.id, Step.seq >= 1)
                    .order_by(Step.seq).all()
                )
            ]
            if not step_texts:
                sub.status = SUPERSEDED
                continue
            graded_sub, _, _ = diagnose_submission(db, student, question, step_texts, reuse=sub)
            review_svc.create_review_if_needed(db, graded_sub)
            graded += 1
        db.commit()
    return graded
