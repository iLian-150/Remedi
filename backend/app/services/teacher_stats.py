# 教师端班级数据助手（v0.5.0 新增）：教师 Agent 工具与「提醒未交学生」接口共用。
# 口径与学生简报一致：一道题「已提交」= 该生有该题的 Submission 或 Essay 记录；
# 一份作业「全部完成」= 作业内每道题都已提交。
from typing import Dict, List, Optional

from ..models import Assignment, Correction, Error, Essay, Question, Submission, User


def _students(db) -> List[User]:
    return db.query(User).filter(User.role == "student").order_by(User.id).all()


def _submitted_qids(db, student_id: int, qids: List[int]) -> set:
    """该生在给定题目集合里已提交的题目 id（数学提交 + 作文提交，与简报口径一致）。"""
    if not qids:
        return set()
    done = {
        s.question_id
        for s in db.query(Submission).filter(
            Submission.student_id == student_id, Submission.question_id.in_(qids)
        ).all()
    }
    done |= {
        e.question_id
        for e in db.query(Essay).filter(
            Essay.student_id == student_id, Essay.question_id.in_(qids)
        ).all()
    }
    return done


def students_not_fully_submitted(db, assignment: Assignment) -> List[User]:
    """未提交全部题目的学生名单（提醒未交 + 教师 Agent 共用）。"""
    qids = [q.id for q in db.query(Question).filter(Question.assignment_id == assignment.id).all()]
    if not qids:
        return []
    missing = []
    for st in _students(db):
        if _submitted_qids(db, st.id, qids) != set(qids):
            missing.append(st)
    return missing


def assignment_status(db, assignment: Assignment) -> Dict:
    """一份作业的提交情况：全部完成 / 部分完成 / 完全没交，三组学生名单。"""
    questions = db.query(Question).filter(Question.assignment_id == assignment.id).all()
    qids = [q.id for q in questions]
    done_all, partial, none = [], [], []
    for st in _students(db):
        done = _submitted_qids(db, st.id, qids)
        if qids and done == set(qids):
            done_all.append(st.name)
        elif done:
            partial.append({"name": st.name, "done": len(done), "total": len(qids)})
        else:
            none.append(st.name)
    return {
        "assignment_id": assignment.id,
        "title": assignment.title,
        "question_count": len(qids),
        "student_total": len(done_all) + len(partial) + len(none),
        "done_all": done_all,
        "partial": partial,
        "none": none,
    }


def find_assignment_by_hint(db, hint: str) -> Optional[Assignment]:
    """按标题关键词匹配一份作业：标题包含关键词，或关键词包含标题；
    匹配不到返回 None（调用方决定是否回退到最近一份）。"""
    hint = (hint or "").strip().strip("《》\"' ")
    if not hint:
        return None
    assignments = db.query(Assignment).order_by(Assignment.id).all()
    for a in assignments:
        if hint in a.title or a.title in hint:
            return a
    return None


def latest_assignment(db) -> Optional[Assignment]:
    return db.query(Assignment).order_by(Assignment.id.desc()).first()


def class_overview(db) -> Dict:
    """班级总览：学生数 / 作业份数 / 累计提交数 / 累计错误数。"""
    return {
        "student_count": db.query(User).filter(User.role == "student").count(),
        "assignment_count": db.query(Assignment).count(),
        "submission_count": db.query(Submission).count(),
        "error_count": db.query(Error).count(),
    }


def uncorrected_overview(db) -> List[Dict]:
    """订正未完成概览：每位学生「出错但尚无一条订正正确」的错题数，降序。
    口径与学生简报的待订正判定一致（corrections 里没有 is_correct=True 即未完成）。"""
    fixed_ids = {
        c.error_id
        for c in db.query(Correction).filter(Correction.is_correct.is_(True)).all()
    }
    rows = []
    for st in _students(db):
        sub_ids = [s.id for s in db.query(Submission).filter(Submission.student_id == st.id).all()]
        if not sub_ids:
            continue
        errs = db.query(Error).filter(Error.submission_id.in_(sub_ids)).all()
        pending = [e for e in errs if e.id not in fixed_ids]
        if pending:
            rows.append({
                "student_id": st.id,
                "student_name": st.name,
                "uncorrected_count": len(pending),
                "knowledge_points": sorted({e.knowledge_point for e in pending}),
            })
    rows.sort(key=lambda x: x["uncorrected_count"], reverse=True)
    return rows
