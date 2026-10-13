# 教师端班级数据助手（v0.5.0 新增）：教师 Agent 工具与「提醒未交学生」接口共用。
# 口径与学生简报一致：一道题「已提交」= 该生有该题的 Submission 或 Essay 记录；
# 一份作业「全部完成」= 作业内每道题都已提交。
from typing import Dict, List, Optional

from sqlalchemy import func

from ..models import Assignment, Correction, Error, Essay, Question, Submission, User


def _students(db) -> List[User]:
    return db.query(User).filter(User.role == "student").order_by(User.id).all()


def _submitted_qids_by_student(db, student_ids: List[int], qids: List[int]) -> Dict[int, set]:
    """批量返回学生在题目集合中的已提交题目，与单学生口径保持一致。"""
    done_by_student = {student_id: set() for student_id in student_ids}
    if not student_ids or not qids:
        return done_by_student
    for student_id, question_id in db.query(
        Submission.student_id, Submission.question_id
    ).join(User, User.id == Submission.student_id).filter(
        User.role == "student", Submission.question_id.in_(qids)
    ).all():
        done_by_student[student_id].add(question_id)
    for student_id, question_id in db.query(
        Essay.student_id, Essay.question_id
    ).join(User, User.id == Essay.student_id).filter(
        User.role == "student", Essay.question_id.in_(qids)
    ).all():
        done_by_student[student_id].add(question_id)
    return done_by_student


def students_not_fully_submitted(db, assignment: Assignment) -> List[User]:
    """未提交全部题目的学生名单（提醒未交 + 教师 Agent 共用）。"""
    qids = [q.id for q in db.query(Question).filter(Question.assignment_id == assignment.id).all()]
    if not qids:
        return []
    students = _students(db)
    done_by_student = _submitted_qids_by_student(
        db, [student.id for student in students], qids
    )
    question_ids = set(qids)
    return [
        student for student in students
        if done_by_student.get(student.id, set()) != question_ids
    ]


def assignment_status(db, assignment: Assignment) -> Dict:
    """一份作业的提交情况：全部完成 / 部分完成 / 完全没交，三组学生名单。"""
    questions = db.query(Question).filter(Question.assignment_id == assignment.id).all()
    qids = [q.id for q in questions]
    students = _students(db)
    done_by_student = _submitted_qids_by_student(
        db, [student.id for student in students], qids
    )
    done_all, partial, none = [], [], []
    for st in students:
        done = done_by_student.get(st.id, set())
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
    has_correct_correction = db.query(Correction.id).filter(
        Correction.error_id == Error.id,
        Correction.student_id == Submission.student_id,
        Correction.is_correct.is_(True),
    ).exists()
    pending_query = (
        db.query(Submission.student_id, Error.knowledge_point)
        .join(Error, Error.submission_id == Submission.id)
        .join(User, User.id == Submission.student_id)
        .filter(User.role == "student", ~has_correct_correction)
    )
    counts_by_student = {
        student_id: (student_name, count)
        for student_id, count in pending_query.with_entities(
            Submission.student_id, User.name, func.count(Error.id)
        ).group_by(Submission.student_id, User.name).all()
    }
    knowledge_points_by_student: Dict[int, set] = {}
    for student_id, knowledge_point in pending_query.with_entities(
        Submission.student_id, Error.knowledge_point
    ).distinct().all():
        knowledge_points_by_student.setdefault(student_id, set()).add(knowledge_point)

    rows = [
        {
            "student_id": student_id,
            "student_name": student_name,
            "uncorrected_count": count,
            "knowledge_points": sorted(knowledge_points_by_student.get(student_id, set())),
        }
        for student_id, (student_name, count) in counts_by_student.items()
    ]
    rows.sort(key=lambda row: (-row["uncorrected_count"], row["student_id"]))
    return rows
