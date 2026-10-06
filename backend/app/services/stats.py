# 班级聚合与学习画像：高频错题 TopN、知识点错误率排行、学生画像。
from typing import Dict, List

from sqlalchemy import func

from ..models import Assignment, Correction, Error, Essay, Question, Submission, User
from .providers import get_provider


def top_error_questions(db, n: int = 10) -> List[Dict]:
    """高频错题 TopN：按 error 数降序。"""
    rows = (
        db.query(
            Question,
            func.count(Error.id).label("error_count"),
            func.count(func.distinct(Submission.student_id)).label("student_count"),
        )
        .join(Submission, Submission.question_id == Question.id)
        .join(Error, Error.submission_id == Submission.id)
        .group_by(Question.id)
        .order_by(func.count(Error.id).desc())
        .limit(n)
        .all()
    )
    return [
        {
            "question_id": q.id,
            "stem": q.stem,
            "subject": q.subject,
            "knowledge_point": q.knowledge_point,
            "error_count": ec,
            "student_count": sc,
        }
        for q, ec, sc in rows
    ]


def knowledge_point_ranking(db) -> List[Dict]:
    """知识点错误率排行。
    口径：submissions = 该知识点题目的提交总数；errors = 该知识点累计 error 数；
    error_rate = errors / submissions。按 error_rate 降序。"""
    # 每个知识点的提交数
    sub_rows = (
        db.query(Question.knowledge_point, func.count(Submission.id).label("submissions"))
        .join(Submission, Submission.question_id == Question.id)
        .group_by(Question.knowledge_point)
        .all()
    )
    submissions_map = {kp: s for kp, s in sub_rows}
    # 每个知识点的错误数
    err_rows = (
        db.query(Error.knowledge_point, func.count(Error.id).label("errors"))
        .group_by(Error.knowledge_point)
        .all()
    )
    items = []
    for kp, ec in err_rows:
        s = submissions_map.get(kp, 0)
        # 同一提交可能产生多条 error（如无法解析+后续错误），错误率上限截断为 1.0
        rate = round(min(1.0, ec / s), 3) if s else 0.0
        items.append({
            "knowledge_point": kp,
            "submissions": s,
            "errors": ec,
            "error_rate": rate,
        })
    items.sort(key=lambda x: x["error_rate"], reverse=True)
    return items


def student_profile(db, student: User) -> Dict:
    """学生画像：知识点掌握度、顽固误区、最近错误、学习建议。"""
    submissions = (
        db.query(Submission).filter(Submission.student_id == student.id).all()
    )
    sub_ids = [s.id for s in submissions]

    # 按知识点聚合：attempts（提交数）、errors（错误数）
    kp_attempts: Dict[str, int] = {}
    kp_errors: Dict[str, int] = {}
    for s in submissions:
        kp = s.question.knowledge_point if s.question else "未知"
        kp_attempts[kp] = kp_attempts.get(kp, 0) + 1
    errors = []
    if sub_ids:
        errors = (
            db.query(Error)
            .filter(Error.submission_id.in_(sub_ids))
            .order_by(Error.created_at.desc())
            .all()
        )
    for e in errors:
        kp_errors[e.knowledge_point] = kp_errors.get(e.knowledge_point, 0) + 1

    knowledge_points = []
    for kp in sorted(set(list(kp_attempts) + list(kp_errors))):
        attempts = kp_attempts.get(kp, 0)
        err_n = kp_errors.get(kp, 0)
        # 同一提交可能产生多条 error，错误率上限截断为 1.0，掌握度下限为 0
        rate = round(min(1.0, err_n / attempts), 3) if attempts else 0.0
        knowledge_points.append({
            "knowledge_point": kp,
            "attempts": attempts,
            "errors": err_n,
            "error_rate": rate,
            "mastery": round(1 - rate, 3),
        })
    knowledge_points.sort(key=lambda x: x["mastery"])

    from .diagnosis import present_error
    from ..models import Step
    stubborn_list = [e for e in errors if e.is_stubborn]
    stubborn_errors = []
    for e in stubborn_list:
        st = db.query(Step).filter(Step.id == e.step_id).first() if e.step_id else None
        stubborn_errors.append({
            "id": e.id,
            "knowledge_point": e.knowledge_point,
            "error_type": e.error_type,
            "step_text": st.text if st else None,
            "created_at": e.created_at,
        })

    recent_errors = [present_error(e, db) for e in errors[:5]]

    suggestion = get_provider().generate_feedback(
        student_name=student.name,
        summary={"knowledge_points": knowledge_points, "stubborn_errors": stubborn_errors},
    )

    return {
        "student": {"id": student.id, "name": student.name,
                    "student_no": student.student_no, "role": student.role},
        "knowledge_points": knowledge_points,
        "stubborn_errors": stubborn_errors,
        "recent_errors": recent_errors,
        "suggestion": suggestion,
    }


def student_briefing(db, student: User) -> Dict:
    """学生首页待办简报：未完成作业 / 待订正 / 需要加固的知识点 / 最近一次批改摘要。
    全部从现有表拼装，不调 LLM（保证首页打开速度与稳定性）。"""
    submissions = (
        db.query(Submission).filter(Submission.student_id == student.id).all()
    )
    sub_ids = [s.id for s in submissions]
    done_qids = {s.question_id for s in submissions}
    done_qids |= {
        e.question_id
        for e in db.query(Essay).filter(
            Essay.student_id == student.id, Essay.question_id.isnot(None)
        ).all()
    }

    # 未完成作业：至少有一道题该生还没提交过
    pending_assignments = []
    for a in db.query(Assignment).order_by(Assignment.id).all():
        questions = db.query(Question).filter(Question.assignment_id == a.id).all()
        remaining = sum(1 for q in questions if q.id not in done_qids)
        if questions and remaining > 0:
            pending_assignments.append({
                "id": a.id,
                "title": a.title,
                "question_count": len(questions),
                "remaining_count": remaining,
                "created_at": a.created_at,
            })

    # 错误集合（待订正判定 + 薄弱点聚合共用）
    errors = []
    if sub_ids:
        errors = (
            db.query(Error)
            .filter(Error.submission_id.in_(sub_ids))
            .order_by(Error.created_at.desc())
            .all()
        )

    # 待订正：尚无一条 is_correct=True 订正的 error
    fixed_ids = {
        c.error_id
        for c in db.query(Correction).filter(
            Correction.student_id == student.id, Correction.is_correct.is_(True)
        ).all()
    }
    pending_errors = [e for e in errors if e.id not in fixed_ids]
    pending_kps = sorted({e.knowledge_point for e in pending_errors})

    # 需要加固的知识点：顽固误区涉及的知识点 ∪ 错误率 ≥ 50% 的知识点
    # （聚合口径与 student_profile 一致；顽固的排前面）
    kp_attempts: Dict[str, int] = {}
    for s in submissions:
        kp = s.question.knowledge_point if s.question else "未知"
        kp_attempts[kp] = kp_attempts.get(kp, 0) + 1
    kp_errors: Dict[str, int] = {}
    stubborn_kps = set()
    for e in errors:
        kp_errors[e.knowledge_point] = kp_errors.get(e.knowledge_point, 0) + 1
        if e.is_stubborn:
            stubborn_kps.add(e.knowledge_point)
    weak_points = sorted(stubborn_kps)
    for kp, attempts in kp_attempts.items():
        if kp in stubborn_kps:
            continue
        rate = kp_errors.get(kp, 0) / attempts if attempts else 0.0
        if rate >= 0.5:
            weak_points.append(kp)

    # 最近一次批改的一句话摘要
    recent_feedback = None
    if submissions:
        latest = max(submissions, key=lambda s: (s.submitted_at, s.id))
        stem = latest.question.stem if latest.question else ""
        latest_errors = [e for e in errors if e.submission_id == latest.id]
        if latest_errors:
            e0 = latest_errors[0]
            detail = e0.detail or f"出现了「{e0.error_type}」"
            recent_feedback = f"最近一次批改《{stem}》：{detail}"
        else:
            recent_feedback = f"最近一次作答《{stem}》全部正确，继续保持！"

    return {
        "pending_assignments": pending_assignments,
        "pending_corrections_count": len(pending_errors),
        "pending_corrections_knowledge_points": pending_kps,
        "weak_points": weak_points,
        "recent_feedback": recent_feedback,
    }


def list_students(db) -> List[Dict]:
    students = db.query(User).filter(User.role == "student").order_by(User.id).all()
    items = []
    for st in students:
        submission_count = db.query(Submission).filter(Submission.student_id == st.id).count()
        error_count = (
            db.query(Error).join(Submission, Error.submission_id == Submission.id)
            .filter(Submission.student_id == st.id).count()
        )
        items.append({
            "id": st.id, "name": st.name, "student_no": st.student_no,
            "submission_count": submission_count, "error_count": error_count,
        })
    return items
