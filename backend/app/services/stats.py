# 班级聚合与学习画像：高频错题 TopN、知识点错误率排行、学生画像。
from typing import Dict, List

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..models import Assignment, AssignmentExt, AssignmentSetting, Correction, Error, Essay, Question, Submission, User, Verification, Workbook


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


def _student_submissions(db, student: User, visible_only: bool):
    """取学生提交列表；学生画像等审核敏感统计可选择只计已审核提交。
    教师端调用一律 visible_only=False，全量可见。"""
    submissions = (
        db.query(Submission)
        .options(joinedload(Submission.question))
        .filter(Submission.student_id == student.id)
        .all()
    )
    if visible_only:
        from .reviews import visible_submissions

        submissions = visible_submissions(db, submissions)
    return submissions


def _profile_suggestion(db, student: User, knowledge_points: List[Dict],
                        stubborn_errors: List[Dict], errors: List) -> str:
    """学习建议（v0.9.1 改本地模板生成，不再同步调 LLM）。

    画像是学生/教师双端高频读接口，线上大模型一次往返要数秒到数十秒，
    页面明显卡顿；建议文案只依赖已算好的画像数据即可拼出：
    先肯定已订正的成果，再点名最弱（仍有待订正错题）的知识点给具体动作
    （订正 → 变式题验证），全部订正完给收尾鼓励，无错题给保持类鼓励。
    口径与前端「老师寄语」一致，学生端措辞用「需要加固」不用「顽固」。"""
    fixed_ids = _fixed_error_ids(db, student)
    corrected = sum(1 for e in errors if e.id in fixed_ids)
    pending = [e for e in errors if e.id not in fixed_ids]
    pending_kps = {e.knowledge_point for e in pending}
    stubborn_kps = {e.get("knowledge_point") for e in stubborn_errors}
    # knowledge_points 已按掌握度升序（最弱在前），取第一个仍有待订正错题的
    weak = next((k for k in knowledge_points if k["knowledge_point"] in pending_kps), None)

    parts = []
    if corrected:
        parts.append(f"已经订正对了 {corrected} 条错题，这股认真劲儿保持住")
    if pending and weak:
        kp = weak["knowledge_point"]
        if kp in stubborn_kps:
            parts.append(f"「{kp}」反复出错、需要加固：先重看一遍规则，把错题订正掉，再做一道变式题验证一下")
        else:
            parts.append(f"眼下最需要补的是「{kp}」：先把它的错题订正掉，再做一道变式题验证，这个知识点就修复啦")
    elif errors and not pending:
        parts.append("错题都订正完了，再做几道变式题验证一下，把知识点彻底修复")
    if not parts:
        parts.append("最近的作业完成得很稳，继续保持；可以试着挑战难一点的综合题")
    return f"{student.name}，" + "；".join(parts) + "。"


def student_profile(db, student: User, visible_only: bool = False) -> Dict:
    """学生画像：知识点掌握度、顽固误区、最近错误、学习建议。"""
    submissions = _student_submissions(db, student, visible_only)
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
            .options(joinedload(Error.step))
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
    stubborn_list = [e for e in errors if e.is_stubborn]
    stubborn_errors = []
    for e in stubborn_list:
        st = e.step if e.step_id else None
        stubborn_errors.append({
            "id": e.id,
            "knowledge_point": e.knowledge_point,
            "error_type": e.error_type,
            "step_text": st.text if st else None,
            "created_at": e.created_at,
        })

    recent_errors = [present_error(e, db, e.step) for e in errors[:5]]

    # v0.9.1：建议改本地模板拼装（见 _profile_suggestion），画像接口不再同步等 LLM
    suggestion = _profile_suggestion(db, student, knowledge_points, stubborn_errors, errors)

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
    submissions = _student_submissions(db, student, visible_only)
    sub_ids = [s.id for s in submissions]

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

    # 已审核错误集合用于学习报告类统计；低置信度错题仍立即进入订正待办。
    errors = []
    if sub_ids:
        errors = (
            db.query(Error)
            .filter(Error.submission_id.in_(sub_ids))
            .order_by(Error.created_at.desc())
            .all()
        )

    correction_sub_ids = sub_ids
    if visible_only:
        correction_sub_ids = [
            row[0] for row in db.query(Submission.id)
            .filter(Submission.student_id == student.id).all()
        ]
    correction_errors = errors
    if correction_sub_ids != sub_ids:
        correction_errors = (
            db.query(Error)
            .filter(Error.submission_id.in_(correction_sub_ids))
            .order_by(Error.created_at.desc())
            .all()
        ) if correction_sub_ids else []

    # 待订正：尚无一条 is_correct=True 订正的 error；与老师复核并行统计。
    fixed_ids = {
        c.error_id
        for c in db.query(Correction).filter(
            Correction.student_id == student.id, Correction.is_correct.is_(True)
        ).all()
    }
    pending_errors = [e for e in correction_errors if e.id not in fixed_ids]
    pending_kps = sorted({e.knowledge_point for e in pending_errors})

    # 需要加固的知识点：顽固误区涉及的知识点 ∪ 错误率 ≥ 50% 的知识点
    # （聚合口径与 student_profile 一致；顽固的排前面）
    kp_attempts: Dict[str, int] = {}
    for s in submissions:
        kp = s.question.knowledge_point if s.question else "未知"
        kp_attempts[kp] = kp_attempts.get(kp, 0) + 1
    kp_errors: Dict[str, int] = {}
    kp_last_error_at = {}
    stubborn_kps = set()
    for e in errors:
        kp_errors[e.knowledge_point] = kp_errors.get(e.knowledge_point, 0) + 1
        last_error_at = kp_last_error_at.get(e.knowledge_point)
        if last_error_at is None or e.created_at > last_error_at:
            kp_last_error_at[e.knowledge_point] = e.created_at
        if e.is_stubborn:
            stubborn_kps.add(e.knowledge_point)
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
        "weak_point_details": weak_point_details,
        "recent_feedback": recent_feedback,
    }


def list_students(db) -> List[Dict]:
    students = db.query(User).filter(User.role == "student").order_by(User.id).all()
    if not students:
        return []
    submission_counts = dict(
        db.query(Submission.student_id, func.count(Submission.id))
        .join(User, User.id == Submission.student_id)
        .filter(User.role == "student")
        .group_by(Submission.student_id)
        .all()
    )
    error_counts = dict(
        db.query(Submission.student_id, func.count(Error.id))
        .join(Error, Error.submission_id == Submission.id)
        .join(User, User.id == Submission.student_id)
        .filter(User.role == "student")
        .group_by(Submission.student_id)
        .all()
    )
    return [{
        "id": st.id,
        "name": st.name,
        "student_no": st.student_no,
        "submission_count": submission_counts.get(st.id, 0),
        "error_count": error_counts.get(st.id, 0),
    } for st in students]


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

def _fixed_error_ids(db, student: User):
    """该生已订正正确的 error id 集合（口径与 student_briefing 一致）。"""
    return {
        c.error_id
        for c in db.query(Correction).filter(
            Correction.student_id == student.id, Correction.is_correct.is_(True)
        ).all()
    }


def _passed_verification_kps(db, student_id: int):
    """该生已通过二次验证的知识点集合（verifications.status = passed）。"""
    return {
        v.knowledge_point
        for v in db.query(Verification).filter(
            Verification.student_id == student_id, Verification.status == "passed"
        ).all()
    }


def _knowledge_point_status(errs, fixed_ids, passed_kps, kp_name: str) -> str:
    """单个知识点的四态判定（学生报告与教师班级修复率共用同一口径）。"""
    if kp_name in passed_kps:
        return "fixed"
    if all(e.id in fixed_ids for e in errs):
        return "awaiting_verify"
    if any(e.is_stubborn for e in errs):
        return "stubborn"
    return "pending"


def student_report(db, student: User, visible_only: bool = False) -> List[Dict]:
    """学生学习报告：按科目聚合提交/正确率/修复进度，并下钻到知识点状态。"""
    submissions = _student_submissions(db, student, visible_only)
    sub_ids = [s.id for s in submissions]
    errors = []
    if sub_ids:
        errors = (
            db.query(Error)
            .filter(Error.submission_id.in_(sub_ids))
            .order_by(Error.created_at.desc())
            .all()
        )
    fixed_ids = _fixed_error_ids(db, student)
    passed_kps = _passed_verification_kps(db, student.id)
    sub_by_id = {s.id: s for s in submissions}

    # 按 (科目, 知识点) 聚合提交数与错题
    attempts: Dict = {}
    kp_errors: Dict = {}
    for s in submissions:
        subject = s.question.subject if s.question else "math"
        kp = s.question.knowledge_point if s.question else "未知"
        attempts[(subject, kp)] = attempts.get((subject, kp), 0) + 1
    for e in errors:
        s = sub_by_id.get(e.submission_id)
        subject = s.question.subject if s and s.question else "math"
        kp_errors.setdefault((subject, e.knowledge_point), []).append(e)

    by_subject: Dict[str, Dict] = {}
    for (subject, kp), errs in kp_errors.items():
        att = attempts.get((subject, kp), 0)
        err_n = len(errs)
        # 错误率口径与学生画像一致：errors / attempts，上限截断 1.0
        rate = round(min(1.0, err_n / att), 3) if att else 0.0
        kp_status = _knowledge_point_status(errs, fixed_ids, passed_kps, kp)
        entry = by_subject.setdefault(subject, {
            "subject": subject,
            "submission_count": 0,
            "error_total": 0,
            "knowledge_points": [],
        })
        entry["knowledge_points"].append({
            "name": kp,
            "attempts": att,
            "error_count": err_n,
            "error_rate": rate,
            "status": kp_status,
            "last_error_at": max(e.created_at for e in errs),
        })

    # 科目层汇总：提交数补全（含从未出错的科目），正确率 = 1 - 错误率（画像同口径）
    for s in submissions:
        subject = s.question.subject if s.question else "math"
        entry = by_subject.setdefault(subject, {
            "subject": subject,
            "submission_count": 0,
            "error_total": 0,
            "knowledge_points": [],
        })
        entry["submission_count"] += 1
    for e in errors:
        s = sub_by_id.get(e.submission_id)
        subject = s.question.subject if s and s.question else "math"
        if subject in by_subject:
            by_subject[subject]["error_total"] += 1

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
    submissions = _student_submissions(db, student, visible_only)
    sub_ids = [s.id for s in submissions]
    if not sub_ids:
        return []
    errors = (
        db.query(Error)
        .options(joinedload(Error.step))
        .filter(Error.submission_id.in_(sub_ids), Error.knowledge_point == knowledge_point)
        .order_by(Error.created_at.desc(), Error.id.desc())
        .all()
    )
    fixed_ids = _fixed_error_ids(db, student)
    sub_by_id = {s.id: s for s in submissions}
    items = []
    for e in errors:
        s = sub_by_id.get(e.submission_id)
        q = s.question if s else None
        step = e.step if e.step_id else None
        items.append({
            "created_at": e.created_at,
            "assignment_title": q.assignment.title if q and q.assignment else "",
            "question_prompt": q.stem if q else "",
            "first_error_seq": step.seq if step else None,
            "error_type": e.error_type,
            "corrected": e.id in fixed_ids,
            "submission_id": e.submission_id,
        })
    return items


# ---------------------------------------------------------------- 班级知识修复率（v0.4.0 新增）
# 全班口径与学生报告一致（四态判定共用 _knowledge_point_status）：
#   班级知识修复率 = 已修复的（学生 × 知识点）组合数 / 出过错的（学生 × 知识点）组合数
#   各知识点修复率 = 该知识点已修复学生数 / 该知识点出过错学生数

def class_repair_rate(db) -> Dict:
    """教师端：班级知识修复率 + 各知识点修复率（只读聚合，不改任何已有口径）。"""
    students = db.query(User).filter(User.role == "student").order_by(User.id).all()
    if not students:
        return {
            "class_repair_rate": 0.0,
            "students_with_errors": 0,
            "total_knowledge_point_pairs": 0,
            "fixed_knowledge_point_pairs": 0,
            "knowledge_points": [],
        }
    errors_by_student: Dict[int, List[Error]] = {}
    for student_id, error in (
        db.query(Submission.student_id, Error)
        .join(Submission, Submission.id == Error.submission_id)
        .join(User, User.id == Submission.student_id)
        .filter(User.role == "student")
        .all()
    ):
        errors_by_student.setdefault(student_id, []).append(error)

    fixed_by_student: Dict[int, set] = {}
    for student_id, error_id in (
        db.query(Correction.student_id, Correction.error_id)
        .join(User, User.id == Correction.student_id)
        .filter(User.role == "student", Correction.is_correct.is_(True))
        .all()
    ):
        fixed_by_student.setdefault(student_id, set()).add(error_id)

    passed_by_student: Dict[int, set] = {}
    for student_id, knowledge_point in (
        db.query(Verification.student_id, Verification.knowledge_point)
        .join(User, User.id == Verification.student_id)
        .filter(User.role == "student", Verification.status == "passed")
        .all()
    ):
        passed_by_student.setdefault(student_id, set()).add(knowledge_point)

    total_pairs = 0
    fixed_pairs = 0
    students_with_errors = 0
    per_kp: Dict[str, Dict] = {}
    for st in students:
        errs = errors_by_student.get(st.id, [])
        if not errs:
            continue
        students_with_errors += 1
        fixed_ids = fixed_by_student.get(st.id, set())
        passed_kps = passed_by_student.get(st.id, set())
        by_kp: Dict[str, List] = {}
        for e in errs:
            by_kp.setdefault(e.knowledge_point, []).append(e)
        for kp, kerrs in by_kp.items():
            status = _knowledge_point_status(kerrs, fixed_ids, passed_kps, kp)
            total_pairs += 1
            cell = per_kp.setdefault(kp, {
                "knowledge_point": kp, "students_errored": 0, "students_fixed": 0,
            })
            cell["students_errored"] += 1
            if status == "fixed":
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
        "students_with_errors": students_with_errors,
        "total_knowledge_point_pairs": total_pairs,
        "fixed_knowledge_point_pairs": fixed_pairs,
        "knowledge_points": kp_items,
    }
