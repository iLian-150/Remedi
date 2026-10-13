# 教师端班级数据助手（v0.5.0 新增）：教师 Agent 工具与「提醒未交学生」接口共用。
# 口径与学生简报一致：一道题「已提交」= 该生有该题的 Submission 或 Essay 记录；
# 一份作业「全部完成」= 作业内每道题都已提交。
from typing import Dict, List, Optional

from sqlalchemy import func, literal, select
from sqlalchemy.orm import load_only

from ..models import Assignment, Correction, Error, Essay, Question, Submission, User


def _submitted_question_pairs(db, assignment_id: int):
    """数据库内合并并去重学生在作业中的提交题目与作文题目。"""
    submission_pairs = select(
        Submission.student_id.label("student_id"),
        Submission.question_id.label("question_id"),
    ).join(
        Question, Question.id == Submission.question_id
    ).join(
        User, User.id == Submission.student_id
    ).where(
        User.role == "student", Question.assignment_id == assignment_id
    )
    essay_pairs = select(
        Essay.student_id.label("student_id"),
        Essay.question_id.label("question_id"),
    ).join(
        Question, Question.id == Essay.question_id
    ).join(
        User, User.id == Essay.student_id
    ).where(
        User.role == "student", Question.assignment_id == assignment_id
    )
    return submission_pairs.union(essay_pairs).subquery()


def students_not_fully_submitted(db, assignment: Assignment) -> List[User]:
    """未提交全部题目的学生名单（提醒未交 + 教师 Agent 共用）。"""
    question_count = select(func.count(Question.id)).where(
        Question.assignment_id == assignment.id
    ).scalar_subquery()
    submitted_pairs = _submitted_question_pairs(db, assignment.id)
    done_counts = (
        select(
            submitted_pairs.c.student_id,
            func.count(submitted_pairs.c.question_id).label("done_count"),
        )
        .group_by(submitted_pairs.c.student_id)
        .subquery()
    )
    return (
        db.query(User)
        .outerjoin(done_counts, done_counts.c.student_id == User.id)
        .filter(
            User.role == "student",
            question_count > 0,
            func.coalesce(done_counts.c.done_count, 0) != question_count,
        )
        .order_by(User.id)
        .all()
    )


def assignment_status(db, assignment: Assignment) -> Dict:
    """一份作业的提交情况：全部完成 / 部分完成 / 完全没交，三组学生名单。"""
    question_count = select(func.count(Question.id)).where(
        Question.assignment_id == assignment.id
    ).scalar_subquery()
    submitted_pairs = _submitted_question_pairs(db, assignment.id)
    done_counts = (
        select(
            submitted_pairs.c.student_id,
            func.count(submitted_pairs.c.question_id).label("done_count"),
        )
        .group_by(submitted_pairs.c.student_id)
        .subquery()
    )
    students = (
        db.query(
            question_count.label("question_count"),
            User.id.label("student_id"),
            User.name.label("student_name"),
            func.coalesce(done_counts.c.done_count, 0).label("done_count"),
        )
        .select_from(select(literal(1).label("singleton")).subquery())
        .outerjoin(User, User.role == "student")
        .outerjoin(done_counts, done_counts.c.student_id == User.id)
        .order_by(User.id)
        .all()
    )
    question_count = int(students[0].question_count or 0) if students else 0
    done_all, partial, none = [], [], []
    for row in students:
        if row.student_id is None:
            continue
        name = row.student_name
        done_count = row.done_count
        if question_count and done_count == question_count:
            done_all.append(name)
        elif done_count:
            partial.append({"name": name, "done": done_count, "total": question_count})
        else:
            none.append(name)
    return {
        "assignment_id": assignment.id,
        "title": assignment.title,
        "question_count": question_count,
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
    assignments = db.query(Assignment).options(
        load_only(Assignment.id, Assignment.title)
    ).order_by(Assignment.id).all()
    for a in assignments:
        if hint in a.title or a.title in hint:
            return a
    return None


def latest_assignment(db) -> Optional[Assignment]:
    return db.query(Assignment).options(
        load_only(Assignment.id, Assignment.title)
    ).order_by(Assignment.id.desc()).first()


def class_overview(db) -> Dict:
    """班级总览：学生数 / 作业份数 / 累计提交数 / 累计错误数。"""
    counts = db.execute(
        select(
            select(func.count(User.id))
            .where(User.role == "student")
            .scalar_subquery()
            .label("student_count"),
            select(func.count(Assignment.id))
            .scalar_subquery()
            .label("assignment_count"),
            select(func.count(Submission.id))
            .scalar_subquery()
            .label("submission_count"),
            select(func.count(Error.id))
            .scalar_subquery()
            .label("error_count"),
        )
    ).one()
    return {
        "student_count": counts.student_count,
        "assignment_count": counts.assignment_count,
        "submission_count": counts.submission_count,
        "error_count": counts.error_count,
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
    counts_by_student = {}
    knowledge_points_by_student: Dict[int, set] = {}
    grouped_rows = pending_query.with_entities(
        Submission.student_id,
        User.name,
        Error.knowledge_point,
        func.count(Error.id),
    ).group_by(
        Submission.student_id, User.name, Error.knowledge_point
    ).all()
    for student_id, student_name, knowledge_point, error_count in grouped_rows:
        current = counts_by_student.get(student_id)
        counts_by_student[student_id] = (
            student_name,
            (current[1] if current else 0) + error_count,
        )
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
