# 班级聚合与学习画像：高频错题 TopN、知识点错误率排行、学生画像。
from typing import Dict, List

from sqlalchemy import case, func, literal, tuple_
from sqlalchemy.orm import joinedload, load_only

from ..models import Assignment, AssignmentExt, AssignmentSetting, Correction, Error, Essay, Question, Step, Submission, SubmissionReview, User, Verification, Workbook


def assignment_ext_fields(db, assignment_id: int) -> Dict:
    """作业扩展字段（v0.5.0）：无 ext 行 = 线上作业，其余字段为 None。
    学生/教师作业列表与详情、学生简报共用同一口径拼装。"""
    ext = db.query(AssignmentExt).filter(AssignmentExt.assignment_id == assignment_id).first()
    # v0.13.1：允许修改开关（assignment_settings，无行 = False）
    setting = db.query(AssignmentSetting).filter(AssignmentSetting.assignment_id == assignment_id).first()
    allow_revision = bool(setting.allow_revision) if setting else False
    if not ext:
        return {"mode": "online", "workbook_title": None, "page_range": None, "deadline": None,
                "allow_revision": allow_revision}
    workbook_title = None
    if ext.workbook_id:
        wb = db.query(Workbook).filter(Workbook.id == ext.workbook_id).first()
        workbook_title = wb.title if wb else None
    return {
        "mode": ext.mode or "online",
        "workbook_title": workbook_title,
        "page_range": ext.page_range,
        "deadline": ext.deadline,
        "allow_revision": allow_revision,
    }


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
    # 将提交数与错因数两组聚合合并为一条 SQL，避免看板和统计接口各自往返两次。
    combined_counts = (
        db.query(
            Question.knowledge_point.label("knowledge_point"),
            func.count(Submission.id).label("submissions"),
            literal(0).label("errors"),
        )
        .join(Submission, Submission.question_id == Question.id)
        .group_by(Question.knowledge_point)
        .union_all(
            db.query(
                Error.knowledge_point.label("knowledge_point"),
                literal(0).label("submissions"),
                func.count(Error.id).label("errors"),
            )
            .group_by(Error.knowledge_point)
        )
        .subquery()
    )
    rows = (
        db.query(
            combined_counts.c.knowledge_point,
            func.sum(combined_counts.c.submissions).label("submissions"),
            func.sum(combined_counts.c.errors).label("errors"),
        )
        .group_by(combined_counts.c.knowledge_point)
        .having(func.sum(combined_counts.c.errors) > 0)
        .all()
    )
    items = []
    for kp, submissions, ec in rows:
        s = int(submissions or 0)
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


def _student_error_query(db, student_id: int, visible_only: bool):
    """该生错因的基础查询；学生自查时在 SQL 中排除待审核提交。"""
    query = db.query(Error).join(
        Submission, Submission.id == Error.submission_id,
    ).filter(Submission.student_id == student_id)
    if visible_only:
        pending_review = db.query(SubmissionReview.submission_id).filter(
            SubmissionReview.submission_id == Submission.id,
            SubmissionReview.status == "pending",
        ).exists()
        query = query.filter(~pending_review)
    return query


def _student_profile_error_stats(db, student_id: int, visible_only: bool):
    """按知识点汇总画像所需错因数、最近时间、顽固数与正确订正数。"""
    has_correct_correction = db.query(Correction.id).filter(
        Correction.error_id == Error.id,
        Correction.student_id == student_id,
        Correction.is_correct.is_(True),
    ).exists()
    rows = _student_error_query(db, student_id, visible_only).with_entities(
        Error.knowledge_point.label("knowledge_point"),
        func.count(Error.id).label("error_count"),
        func.max(Error.created_at).label("last_error_at"),
        func.max(case((Error.is_stubborn.is_(True), 1), else_=0)).label(
            "stubborn_count"
        ),
        func.sum(case((has_correct_correction, 1), else_=0)).label(
            "corrected_count"
        ),
    ).group_by(Error.knowledge_point).all()
    return {
        row.knowledge_point: (
            int(row.error_count),
            row.last_error_at,
            bool(row.stubborn_count),
            int(row.corrected_count or 0),
        )
        for row in rows
    }


def _student_stubborn_errors(db, student_id: int, visible_only: bool):
    """只读取画像实际展示的顽固错因摘要行。"""
    return (
        _student_error_query(db, student_id, visible_only)
        .filter(Error.is_stubborn.is_(True))
        .with_entities(
            Error.id.label("id"),
            Error.knowledge_point.label("knowledge_point"),
            Error.error_type.label("error_type"),
            Error.step_id.label("step_id"),
            Error.created_at.label("created_at"),
        )
        .order_by(Error.created_at.desc(), Error.id.desc())
        .all()
    )


def _student_attempt_counts(db, student_id: int, visible_only: bool) -> Dict[str, int]:
    """按知识点聚合提交数；学生自查口径会在数据库中排除待审核提交。"""
    knowledge_point = case(
        (Question.id.is_(None), "未知"),
        else_=Question.knowledge_point,
    )
    query = (
        db.query(knowledge_point.label("knowledge_point"), func.count(Submission.id))
        .select_from(Submission)
        .outerjoin(Question, Question.id == Submission.question_id)
        .filter(Submission.student_id == student_id)
    )
    if visible_only:
        query = query.outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        ).filter(
            func.coalesce(SubmissionReview.status, "approved") != "pending"
        )
    return {
        kp: int(attempts)
        for kp, attempts in query.group_by(knowledge_point).all()
    }


def _student_error_stats(db, student_id: int, visible_only: bool):
    """按知识点聚合错因数、最近时间与顽固标记。"""
    query = (
        db.query(
            Error.knowledge_point,
            func.count(Error.id),
            func.max(Error.created_at),
            func.max(case((Error.is_stubborn.is_(True), 1), else_=0)),
        )
        .join(Submission, Submission.id == Error.submission_id)
        .filter(Submission.student_id == student_id)
    )
    if visible_only:
        query = query.outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        ).filter(
            func.coalesce(SubmissionReview.status, "approved") != "pending"
        )
    return {
        kp: (int(error_count), last_error_at, bool(has_stubborn))
        for kp, error_count, last_error_at, has_stubborn
        in query.group_by(Error.knowledge_point).all()
    }


def _profile_suggestion(student: User, knowledge_points: List[Dict],
                        stubborn_kps: set, error_count: int,
                        corrected_count: int, pending_kps: set) -> str:
    """学习建议（v0.9.1 改本地模板生成，不再同步调 LLM）。

    画像是学生/教师双端高频读接口，线上大模型一次往返要数秒到数十秒，
    页面明显卡顿；建议文案只依赖已算好的画像数据即可拼出：
    先肯定已订正的成果，再点名最弱（仍有待订正错题）的知识点给具体动作
    （订正 → 变式题验证），全部订正完给收尾鼓励，无错题给保持类鼓励。
    口径与前端「老师寄语」一致，学生端措辞用「需要加固」不用「顽固」。"""
    # knowledge_points 已按掌握度升序（最弱在前），取第一个仍有待订正错题的
    weak = next((k for k in knowledge_points if k["knowledge_point"] in pending_kps), None)

    parts = []
    if corrected_count:
        parts.append(f"已经订正对了 {corrected_count} 条错题，这股认真劲儿保持住")
    if pending_kps and weak:
        kp = weak["knowledge_point"]
        if kp in stubborn_kps:
            parts.append(f"「{kp}」反复出错、需要加固：先重看一遍规则，把错题订正掉，再做一道变式题验证一下")
        else:
            parts.append(f"眼下最需要补的是「{kp}」：先把它的错题订正掉，再做一道变式题验证，这个知识点就修复啦")
    elif error_count and not pending_kps:
        parts.append("错题都订正完了，再做几道变式题验证一下，把知识点彻底修复")
    if not parts:
        parts.append("最近的作业完成得很稳，继续保持；可以试着挑战难一点的综合题")
    return f"{student.name}，" + "；".join(parts) + "。"


def student_profile(db, student: User, visible_only: bool = False) -> Dict:
    """学生画像：知识点掌握度、顽固误区、最近错误、学习建议。"""
    # 按知识点聚合：attempts（提交数）、errors（错误数）
    kp_attempts = _student_attempt_counts(db, student.id, visible_only)
    kp_error_stats = _student_profile_error_stats(db, student.id, visible_only)
    kp_errors = {kp: stats[0] for kp, stats in kp_error_stats.items()}
    total_errors = sum(stats[0] for stats in kp_error_stats.values())
    corrected_count = sum(stats[3] for stats in kp_error_stats.values())
    pending_kps = {
        kp for kp, stats in kp_error_stats.items() if stats[3] < stats[0]
    }
    stubborn_kps = {
        kp for kp, stats in kp_error_stats.items() if stats[2]
    }

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
    stubborn_list = _student_stubborn_errors(db, student.id, visible_only)
    stubborn_step_ids = list({e.step_id for e in stubborn_list if e.step_id is not None})
    step_text_by_id = {}
    for start in range(0, len(stubborn_step_ids), 500):
        for step_id, step_text in db.query(Step.id, Step.text).filter(
            Step.id.in_(stubborn_step_ids[start:start + 500])
        ).all():
            step_text_by_id[step_id] = step_text
    stubborn_errors = []
    for e in stubborn_list:
        stubborn_errors.append({
            "id": e.id,
            "knowledge_point": e.knowledge_point,
            "error_type": e.error_type,
            "step_text": step_text_by_id.get(e.step_id),
            "created_at": e.created_at,
        })

    recent_errors = _student_error_query(
        db, student.id, visible_only,
    ).options(
        joinedload(Error.step).load_only(Step.id, Step.seq, Step.text)
    ).order_by(
        Error.created_at.desc(), Error.id.desc(),
    ).limit(5).all()
    recent_errors = [
        present_error(error, db, error.step) for error in recent_errors
    ]

    # v0.9.1：建议改本地模板拼装（见 _profile_suggestion），画像接口不再同步等 LLM
    suggestion = _profile_suggestion(
        student, knowledge_points, stubborn_kps, total_errors,
        corrected_count, pending_kps,
    )

    return {
        "student": {"id": student.id, "name": student.name,
                    "student_no": student.student_no, "role": student.role},
        "knowledge_points": knowledge_points,
        "stubborn_errors": stubborn_errors,
        "recent_errors": recent_errors,
        "suggestion": suggestion,
    }


def student_briefing(db, student: User, visible_only: bool = False) -> Dict:
    """学生首页待办简报：未完成作业 / 待订正 / 需要加固的知识点 / 最近一次批改摘要。
    全部从现有表拼装，不调 LLM（保证首页打开速度与稳定性）。"""
    kp_attempts = _student_attempt_counts(db, student.id, visible_only)
    latest_submission_query = db.query(Submission.id).filter(
        Submission.student_id == student.id
    )
    if visible_only:
        latest_submission_query = latest_submission_query.outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        ).filter(
            func.coalesce(SubmissionReview.status, "approved") != "pending"
        )
    latest_submission_row = latest_submission_query.order_by(
        Submission.submitted_at.desc(), Submission.id.desc()
    ).first()
    latest_submission_id = latest_submission_row[0] if latest_submission_row else None

    # 未完成作业：批量读取作业、题目数与扩展信息，避免按作业逐条查库。
    # 与学生作业列表保持相同可见范围：学生自主上传题目只归上传者练习，不进入班级作业简报。
    visible_assignment = (
        Assignment.created_by.is_(None)
        | (~Assignment.created_by.in_(
            db.query(User.id).filter(User.role == "student")
        ))
    )
    # 每题最多计一次；UNION 同时包含待审核提交和作文，保持“交过即完成”的原有口径，
    # 并让数据库直接汇总，避免把全班作业的题目 ID 载入 Python 后逐题扫描。
    done_question_ids = (
        db.query(Submission.question_id.label("question_id"))
        .filter(Submission.student_id == student.id)
        .union(
            db.query(Essay.question_id.label("question_id")).filter(
                Essay.student_id == student.id,
                Essay.question_id.isnot(None),
            )
        )
        .subquery()
    )
    question_stats = (
        db.query(
            Question.assignment_id.label("assignment_id"),
            func.count(Question.id).label("question_count"),
            func.count(done_question_ids.c.question_id).label("submitted_count"),
        )
        .join(Assignment, Assignment.id == Question.assignment_id)
        .outerjoin(done_question_ids, done_question_ids.c.question_id == Question.id)
        .filter(visible_assignment)
        .group_by(Question.assignment_id)
        .subquery()
    )
    assignment_rows = (
        db.query(
            Assignment,
            AssignmentExt,
            AssignmentSetting,
            Workbook.title,
            func.coalesce(question_stats.c.question_count, 0),
            func.coalesce(question_stats.c.submitted_count, 0),
        )
        .outerjoin(AssignmentExt, AssignmentExt.assignment_id == Assignment.id)
        .outerjoin(AssignmentSetting, AssignmentSetting.assignment_id == Assignment.id)
        .outerjoin(Workbook, Workbook.id == AssignmentExt.workbook_id)
        .outerjoin(question_stats, question_stats.c.assignment_id == Assignment.id)
        .filter(visible_assignment)
        .order_by(Assignment.id)
        .all()
    )

    pending_assignments = []
    for a, ext, setting, workbook_title, question_count, submitted_count in assignment_rows:
        question_count = int(question_count)
        remaining = question_count - int(submitted_count)
        if question_count > 0 and remaining > 0:
            pending_assignments.append({
                "id": a.id,
                "title": a.title,
                "question_count": question_count,
                "remaining_count": remaining,
                "created_at": a.created_at,
                "mode": (ext.mode or "online") if ext else "online",
                "workbook_title": workbook_title if ext and ext.workbook_id else None,
                "page_range": ext.page_range if ext else None,
                "deadline": ext.deadline if ext else None,
                "allow_revision": bool(setting.allow_revision) if setting else False,
            })

    # 待订正仍统计待审核提交；分组计数并用 NOT EXISTS 排除已有正确订正。
    has_correct_correction = db.query(Correction.id).filter(
        Correction.error_id == Error.id,
        Correction.student_id == student.id,
        Correction.is_correct.is_(True),
    ).exists()
    pending_correction_rows = (
        db.query(Error.knowledge_point, func.count(Error.id))
        .join(Submission, Submission.id == Error.submission_id)
        .filter(Submission.student_id == student.id, ~has_correct_correction)
        .group_by(Error.knowledge_point)
        .all()
    )
    pending_corrections_count = sum(count for _, count in pending_correction_rows)
    pending_kps = sorted(kp for kp, count in pending_correction_rows if count)

    # 需要加固的知识点：顽固误区涉及的知识点 ∪ 错误率 ≥ 50% 的知识点
    # （聚合口径与 student_profile 一致；顽固的排前面）
    kp_error_stats = _student_error_stats(db, student.id, visible_only)
    kp_errors = {kp: stats[0] for kp, stats in kp_error_stats.items()}
    kp_last_error_at = {kp: stats[1] for kp, stats in kp_error_stats.items()}
    stubborn_kps = {kp for kp, stats in kp_error_stats.items() if stats[2]}
    weak_points = sorted(stubborn_kps)
    for kp, attempts in kp_attempts.items():
        if kp in stubborn_kps:
            continue
        rate = kp_errors.get(kp, 0) / attempts if attempts else 0.0
        if rate >= 0.5:
            weak_points.append(kp)

    # 需加固知识点的明细（v0.2.1 新增字段，供简报卡片展示出错次数/最近出错时间）
    weak_point_details = []
    for kp in weak_points:
        weak_point_details.append({
            "knowledge_point": kp,
            "error_count": kp_errors.get(kp, 0),
            "last_error_at": kp_last_error_at.get(kp),
        })

    # 最近一次批改的一句话摘要
    recent_feedback = None
    if latest_submission_id is not None:
        feedback_row = (
            db.query(Question.stem, Error.detail, Error.error_type)
            .select_from(Submission)
            .outerjoin(Question, Question.id == Submission.question_id)
            .outerjoin(Error, Error.submission_id == Submission.id)
            .filter(Submission.id == latest_submission_id)
            .order_by(Error.created_at.desc())
            .first()
        )
        stem = (feedback_row.stem if feedback_row else None) or ""
        if feedback_row is not None and feedback_row.error_type is not None:
            detail = feedback_row.detail or f"出现了「{feedback_row.error_type}」"
            recent_feedback = f"最近一次批改《{stem}》：{detail}"
        else:
            recent_feedback = f"最近一次作答《{stem}》全部正确，继续保持！"

    return {
        "pending_assignments": pending_assignments,
        "pending_corrections_count": pending_corrections_count,
        "pending_corrections_knowledge_points": pending_kps,
        "weak_points": weak_points,
        "weak_point_details": weak_point_details,
        "recent_feedback": recent_feedback,
    }


def list_students(db) -> List[Dict]:
    rows = (
        db.query(
            User.id,
            User.name,
            User.student_no,
            func.count(func.distinct(Submission.id)),
            func.count(Error.id),
        )
        .outerjoin(Submission, Submission.student_id == User.id)
        .outerjoin(Error, Error.submission_id == Submission.id)
        .filter(User.role == "student")
        .group_by(User.id, User.name, User.student_no)
        .order_by(User.id)
        .all()
    )
    return [{
        "id": student_id,
        "name": name,
        "student_no": student_no,
        "submission_count": submission_count,
        "error_count": error_count,
    } for student_id, name, student_no, submission_count, error_count in rows]


# ---------------------------------------------------------------- 学习报告（v0.2.1 新增）
# 对应开题报告「学习记忆层 + 教学反馈层」：科目 → 知识点 → 错题时间线 → 步骤诊断 四级下钻。
# 知识点状态口径（v0.4.0 升级为四态）：
#   fixed           —— 已通过该知识点的二次验证（verifications 有 passed 记录）
#   awaiting_verify —— 错题已全部订正正确，但尚未通过二次验证
#   stubborn        —— 命中既有顽固判定（该知识点任一错题 is_stubborn=True，即诊断时
#                      check_stubborn 命中：同知识点在窗口天数内重复出错），且仍有未订正错题
#   pending         —— 其余有未订正错题的情况
# 【口径变更】v0.3 及以前「错题全订正即 fixed」已废弃：订正对了只是把这一步改对，
# 必须再独立做对一道同知识点变式题（二次验证）才算修复。
# 知识修复率 fixed_ratio = fixed 知识点数 / 出过错知识点数（与本口径配套）。

def _fixed_error_ids(db, student: User, error_ids: List[int]):
    """批量读取指定错题中该生已订正正确的 ID，不加载订正正文或无关历史行。"""
    fixed_ids = set()
    # SQLite 对单条语句的绑定变量数有限，分块查询以兼容学生的长历史记录。
    for start in range(0, len(error_ids), 500):
        rows = (
            db.query(Correction.error_id)
            .filter(
                Correction.student_id == student.id,
                Correction.is_correct.is_(True),
                Correction.error_id.in_(error_ids[start:start + 500]),
            )
            .all()
        )
        fixed_ids.update(error_id for (error_id,) in rows)
    return fixed_ids


def student_report(db, student: User, visible_only: bool = False) -> List[Dict]:
    """学生学习报告：按科目聚合提交/正确率/修复进度，并下钻到知识点状态。"""
    subject_expr = case(
        (Question.id.is_(None), "math"), else_=Question.subject,
    )
    knowledge_point_expr = case(
        (Question.id.is_(None), "未知"), else_=Question.knowledge_point,
    )
    pending_review = db.query(SubmissionReview.submission_id).filter(
        SubmissionReview.submission_id == Submission.id,
        SubmissionReview.status == "pending",
    ).exists()

    attempt_query = (
        db.query(
            subject_expr.label("subject"),
            knowledge_point_expr.label("knowledge_point"),
            func.count(Submission.id).label("attempt_count"),
        )
        .select_from(Submission)
        .outerjoin(Question, Question.id == Submission.question_id)
        .filter(Submission.student_id == student.id)
    )
    if visible_only:
        attempt_query = attempt_query.filter(~pending_review)
    attempt_rows = attempt_query.group_by(
        subject_expr, knowledge_point_expr,
    ).all()
    attempts = {
        (row.subject, row.knowledge_point): int(row.attempt_count)
        for row in attempt_rows
    }

    has_correct_correction = db.query(Correction.id).filter(
        Correction.error_id == Error.id,
        Correction.student_id == student.id,
        Correction.is_correct.is_(True),
    ).exists()
    error_query = (
        db.query(
            subject_expr.label("subject"),
            Error.knowledge_point.label("knowledge_point"),
            func.count(Error.id).label("error_count"),
            func.sum(case((Error.is_stubborn.is_(True), 1), else_=0)).label(
                "stubborn_count"
            ),
            func.sum(case((has_correct_correction, 1), else_=0)).label(
                "corrected_count"
            ),
            func.max(Error.created_at).label("last_error_at"),
        )
        .join(Submission, Submission.id == Error.submission_id)
        .outerjoin(Question, Question.id == Submission.question_id)
        .filter(Submission.student_id == student.id)
    )
    if visible_only:
        error_query = error_query.filter(~pending_review)
    error_rows = error_query.group_by(
        subject_expr, Error.knowledge_point,
    ).order_by(func.max(Error.created_at).desc()).all()

    error_knowledge_points = {row.knowledge_point for row in error_rows}
    passed_kps = set()
    knowledge_point_list = list(error_knowledge_points)
    for start in range(0, len(knowledge_point_list), 400):
        passed_kps.update(
            knowledge_point
            for (knowledge_point,) in db.query(Verification.knowledge_point).filter(
                Verification.student_id == student.id,
                Verification.status == "passed",
                Verification.knowledge_point.in_(knowledge_point_list[start:start + 400]),
            ).all()
        )

    # 报告只下发聚合结果；提交数、错因状态与时间均由数据库按组返回。
    by_subject: Dict[str, Dict] = {}
    for (subject, _knowledge_point), attempt_count in attempts.items():
        entry = by_subject.setdefault(subject, {
            "subject": subject,
            "submission_count": 0,
            "error_total": 0,
            "knowledge_points": [],
        })
        entry["submission_count"] += attempt_count

    for row in error_rows:
        error_count = int(row.error_count)
        corrected_count = int(row.corrected_count or 0)
        if row.knowledge_point in passed_kps:
            status = "fixed"
        elif corrected_count == error_count:
            status = "awaiting_verify"
        elif int(row.stubborn_count or 0) > 0:
            status = "stubborn"
        else:
            status = "pending"

        attempt_count = attempts.get((row.subject, row.knowledge_point), 0)
        entry = by_subject[row.subject]
        entry["error_total"] += error_count
        entry["knowledge_points"].append({
            "name": row.knowledge_point,
            "attempts": attempt_count,
            "error_count": error_count,
            "error_rate": round(
                min(1.0, error_count / attempt_count), 3
            ) if attempt_count else 0.0,
            "status": status,
            "last_error_at": row.last_error_at,
        })

    result = []
    for subject in sorted(by_subject):
        entry = by_subject[subject]
        kps = sorted(entry["knowledge_points"], key=lambda x: x["error_rate"], reverse=True)
        att_total = entry["submission_count"]
        err_total = entry["error_total"]
        correct_rate = round(1 - min(1.0, err_total / att_total), 3) if att_total else 1.0
        fixed_n = sum(1 for k in kps if k["status"] == "fixed")
        result.append({
            "subject": subject,
            "submission_count": att_total,
            "correct_rate": correct_rate,
            "pending_fix_count": sum(1 for k in kps if k["status"] != "fixed"),
            "fixed_ratio": round(fixed_n / len(kps), 3) if kps else 1.0,
            "knowledge_points": kps,
        })
    return result


def knowledge_point_errors(db, student: User, knowledge_point: str,
                           visible_only: bool = False) -> List[Dict]:
    """某知识点下该生的错题时间线（纵向学习记忆），按时间倒序。"""
    query = (
        db.query(Error, Submission, Question, Assignment, Step)
        .join(Submission, Error.submission_id == Submission.id)
        .outerjoin(Question, Submission.question_id == Question.id)
        .outerjoin(Assignment, Question.assignment_id == Assignment.id)
        .outerjoin(Step, Error.step_id == Step.id)
        .options(
            load_only(
                Error.id, Error.submission_id, Error.knowledge_point,
                Error.error_type, Error.step_id, Error.created_at,
            ),
            load_only(Submission.id),
            load_only(Question.id, Question.stem),
            load_only(Assignment.id, Assignment.title),
            load_only(Step.id, Step.seq, Step.text),
        )
        .filter(
            Submission.student_id == student.id,
            Error.knowledge_point == knowledge_point,
        )
        .order_by(Error.created_at.desc(), Error.id.desc())
    )
    if visible_only:
        pending_review = db.query(SubmissionReview.submission_id).filter(
            SubmissionReview.submission_id == Submission.id,
            SubmissionReview.status == "pending",
        ).exists()
        query = query.filter(~pending_review)

    rows = query.all()
    if not rows:
        return []
    fixed_ids = _fixed_error_ids(
        db, student, [error.id for error, _, _, _, _ in rows]
    )
    items = []
    for error, submission, question, assignment, step in rows:
        items.append({
            "created_at": error.created_at,
            "assignment_title": assignment.title if assignment else "",
            "question_prompt": question.stem if question else "",
            "first_error_seq": step.seq if step else None,
            "error_type": error.error_type,
            "corrected": error.id in fixed_ids,
            "submission_id": submission.id,
        })
    return items


# ---------------------------------------------------------------- 班级知识修复率（v0.4.0 新增）
# 全班口径与学生报告一致（共用四态判定规则）：
#   班级知识修复率 = 已修复的（学生 × 知识点）组合数 / 出过错的（学生 × 知识点）组合数
#   各知识点修复率 = 该知识点已修复学生数 / 该知识点出过错学生数

def class_repair_rate(db) -> Dict:
    """教师端：班级知识修复率 + 各知识点修复率（只读聚合，不改任何已有口径）。"""
    # 先在数据库按学生和知识点汇总，避免把每条错题及订正正文读入 Python。
    error_summaries = (
        db.query(
            Submission.student_id.label("student_id"),
            Error.knowledge_point.label("knowledge_point"),
            func.count(Error.id).label("error_count"),
            func.sum(case((Error.is_stubborn.is_(True), 1), else_=0)).label(
                "stubborn_count"
            ),
        )
        .join(Error, Error.submission_id == Submission.id)
        .join(User, User.id == Submission.student_id)
        .filter(User.role == "student")
        .group_by(Submission.student_id, Error.knowledge_point)
        .all()
    )
    if not error_summaries:
        return {
            "class_repair_rate": 0.0,
            "students_with_errors": 0,
            "total_knowledge_point_pairs": 0,
            "fixed_knowledge_point_pairs": 0,
            "knowledge_points": [],
        }

    # 仅统计这些错题组合中已有正确订正的错误；distinct 保留重复订正只计一次的口径。
    fixed_counts = dict(
        (
            (student_id, knowledge_point),
            int(fixed_count),
        )
        for student_id, knowledge_point, fixed_count in (
            db.query(
                Submission.student_id,
                Error.knowledge_point,
                func.count(func.distinct(Error.id)),
            )
            .join(Error, Error.submission_id == Submission.id)
            .join(User, User.id == Submission.student_id)
            .join(Correction, Correction.error_id == Error.id)
            .filter(
                User.role == "student",
                Correction.student_id == Submission.student_id,
                Correction.is_correct.is_(True),
            )
            .group_by(Submission.student_id, Error.knowledge_point)
            .all()
        )
    )

    error_pairs = [
        (summary.student_id, summary.knowledge_point)
        for summary in error_summaries
    ]
    passed_pairs = set()
    # 只加载有错题的学生-知识点组合，并分块控制 SQLite 的绑定参数数量。
    for start in range(0, len(error_pairs), 400):
        pair_chunk = error_pairs[start:start + 400]
        for student_id, knowledge_point in (
            db.query(Verification.student_id, Verification.knowledge_point)
            .filter(
                tuple_(Verification.student_id, Verification.knowledge_point).in_(pair_chunk),
                Verification.status == "passed",
            )
            .distinct()
            .all()
        ):
            passed_pairs.add((student_id, knowledge_point))

    total_pairs = 0
    fixed_pairs = 0
    students_with_errors = {summary.student_id for summary in error_summaries}
    per_kp: Dict[str, Dict] = {}
    for summary in error_summaries:
        student_id = summary.student_id
        kp = summary.knowledge_point
        pair = (student_id, kp)
        is_fixed = (
            pair in passed_pairs
            or fixed_counts.get(pair, 0) == summary.error_count
        )
        total_pairs += 1
        cell = per_kp.setdefault(kp, {
            "knowledge_point": kp, "students_errored": 0, "students_fixed": 0,
        })
        cell["students_errored"] += 1
        if is_fixed:
            fixed_pairs += 1
            cell["students_fixed"] += 1
    kp_items = []
    for cell in per_kp.values():
        kp_items.append({
            **cell,
            "repair_rate": round(cell["students_fixed"] / cell["students_errored"], 3)
            if cell["students_errored"] else 0.0,
        })
    # 修复率低的排前面（最需要教学干预的知识点置顶），同率按出错学生数降序
    kp_items.sort(key=lambda x: (x["repair_rate"], -x["students_errored"]))
    return {
        "class_repair_rate": round(fixed_pairs / total_pairs, 3) if total_pairs else 0.0,
        "students_with_errors": len(students_with_errors),
        "total_knowledge_point_pairs": total_pairs,
        "fixed_knowledge_point_pairs": fixed_pairs,
        "knowledge_points": kp_items,
    }
