# 评分系统：AI 初评分 + 教师审核定分。
#
# 计分公式（透明口径，审核详情里同文案展示给老师）：
#   题目满分 = 作业总分 × 该题分值占比% / 100
#     - 作业总分：assignment_scoring.total_score，无配置行 = 100
#     - 分值占比：question_weights.weight_pct，无配置行 = 100 / 该作业题数（均分）
#   得分率 = 正确步骤数 / 作答步骤总数
#     - 只数学生作答步（seq ≥ 1，不含 seq=0 题干）
#     - ok 计正确；error / unparseable 计入作答步但不计正确；skipped 不参与统计
#     - 全部步骤都对 → 得分率 1.0；没有有效作答步骤 → 得分率 0
#   AI 初评分 = round(题目满分 × 得分率, 1)
#
# 批改结果立即展示 AI 分；低于作业审核线时教师可改判并写入 final_score。
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, load_only

from ..models import (
    Assignment,
    AssignmentScoring,
    Question,
    QuestionWeight,
    Step,
    Submission,
    SubmissionReview,
    SubmissionScore,
)

DEFAULT_TOTAL = 100.0


# ---------------------------------------------------------------- 配置读取

def assignment_total(db: Session, assignment_id: int) -> float:
    """作业总分：有配置行用配置，无配置行 = 100。"""
    row = db.query(AssignmentScoring).filter(
        AssignmentScoring.assignment_id == assignment_id
    ).first()
    return float(row.total_score) if row and row.total_score else DEFAULT_TOTAL


def effective_weight_pct(db: Session, question: Question) -> float:
    """题目分值占比（%）：有配置行用配置，无配置行 = 100 / 该作业题数（均分）。"""
    row = db.query(QuestionWeight).filter(
        QuestionWeight.question_id == question.id
    ).first()
    if row is not None:
        return float(row.weight_pct)
    count = db.query(Question).filter(
        Question.assignment_id == question.assignment_id
    ).count()
    return 100.0 / count if count else 100.0


def question_max_score(db: Session, question: Question) -> float:
    """题目满分 = 作业总分 × 分值占比% / 100（保留 1 位小数，与得分同精度）。"""
    total = assignment_total(db, question.assignment_id)
    return round(total * effective_weight_pct(db, question) / 100.0, 1)


def set_assignment_scoring(db: Session, assignment_id: int,
                           total_score: Optional[float],
                           weights: List[Tuple[int, Optional[float]]], *,
                           is_new: bool = False) -> None:
    """发布作业时落库分值配置（调用方负责 commit）：
    total_score 为 None 时不写总分行（走默认 100）；weights 里 pct 为 None 的题不写行（走均分）。"""
    if is_new:
        if total_score is not None:
            db.add(AssignmentScoring(
                assignment_id=assignment_id,
                total_score=float(total_score),
            ))
        db.add_all(
            QuestionWeight(question_id=question_id, weight_pct=float(pct))
            for question_id, pct in weights
            if pct is not None
        )
        return

    if total_score is not None:
        row = db.query(AssignmentScoring).filter(
            AssignmentScoring.assignment_id == assignment_id
        ).first()
        if row is None:
            db.add(AssignmentScoring(assignment_id=assignment_id,
                                     total_score=float(total_score)))
        else:
            row.total_score = float(total_score)
    specified_weights = [
        (question_id, pct) for question_id, pct in weights if pct is not None
    ]
    existing_weights = {}
    if specified_weights:
        question_ids = [question_id for question_id, _ in specified_weights]
        existing_weights = {
            row.question_id: row
            for row in db.query(QuestionWeight).filter(
                QuestionWeight.question_id.in_(question_ids)
            ).all()
        }
    for question_id, pct in specified_weights:
        row = existing_weights.get(question_id)
        if row is None:
            db.add(QuestionWeight(question_id=question_id, weight_pct=float(pct)))
        else:
            row.weight_pct = float(pct)


# ---------------------------------------------------------------- AI 初评分

def step_counts(steps: List[Step]) -> Tuple[int, int]:
    """(正确步数, 已判定作答步总数)：不把首个错误后跳过的步骤算成错题。"""
    answer_steps = [
        s for s in steps
        if s.seq >= 1 and s.status in {"ok", "error", "unparseable"}
    ]
    ok = sum(1 for s in answer_steps if s.status == "ok")
    return ok, len(answer_steps)


def compute_ai_score(db: Session, submission: Submission,
                     steps: Optional[List[Step]] = None) -> Dict:
    """按公式算一份提交的 AI 初评分（不落库）。返回满分/得分/步数明细，
    审核详情据此向老师解释「满分 X · 步骤对了 a/b 步」。"""
    question = submission.question
    max_score = question_max_score(db, question) if question else 0.0
    if steps is None:
        steps = (
            db.query(Step).filter(Step.submission_id == submission.id)
            .order_by(Step.seq).all()
        )
    ok, total = step_counts(steps)
    rate = (ok / total) if total else 0.0
    return {
        "max_score": max_score,
        "ai_score": round(max_score * rate, 1),
        "ok_steps": ok,
        "total_steps": total,
        "rate": rate,
    }


def persist_ai_score(db: Session, submission: Submission,
                     steps: Optional[List[Step]] = None) -> SubmissionScore:
    """批改落库的共用路径调用：把 AI 初评分写入 submission_scores（幂等 upsert，
    重复批改同一提交时只更新 ai_score，不动已落定的 final_score）。"""
    info = compute_ai_score(db, submission, steps)
    row = db.query(SubmissionScore).filter(
        SubmissionScore.submission_id == submission.id
    ).first()
    if row is None:
        row = SubmissionScore(submission_id=submission.id,
                              ai_score=info["ai_score"])
        db.add(row)
    else:
        row.ai_score = info["ai_score"]
        row.updated_at = datetime.now()
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit
    return row


def ensure_score(db: Session, submission: Submission) -> SubmissionScore:
    """分数行不存在时按公式补算落库（历史提交/种子数据兜底），存在则直接返回。"""
    row = db.query(SubmissionScore).filter(
        SubmissionScore.submission_id == submission.id
    ).first()
    if row is not None:
        return row
    return persist_ai_score(db, submission)


def get_score_row(db: Session, submission_id: int) -> Optional[SubmissionScore]:
    return db.query(SubmissionScore).filter(
        SubmissionScore.submission_id == submission_id
    ).first()


def finalize_on_approve(db: Session, submission: Submission, teacher,
                        final_score: Optional[float] = None,
                        *, commit: bool = True) -> SubmissionScore:
    """教师审核通过时落定最终分：老师给了分就用老师的（调用方已做 0~满分校验），
    没给则 final = ai。已有 final 不覆盖老师先前定的分（除非本次显式给了新分）。"""
    row = db.query(SubmissionScore).filter(
        SubmissionScore.submission_id == submission.id
    ).first()
    if row is None:
        info = compute_ai_score(db, submission)
        row = SubmissionScore(
            submission_id=submission.id,
            ai_score=info["ai_score"],
        )
        db.add(row)
    if final_score is not None:
        row.final_score = round(float(final_score), 1)
        row.updated_by = teacher.id
    elif row.final_score is None:
        row.final_score = row.ai_score
        row.updated_by = teacher.id
    row.updated_at = datetime.now()
    if commit:
        expire_on_commit = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.commit()
        finally:
            db.expire_on_commit = expire_on_commit
    return row


def visible_score(db: Session, submission: Submission) -> Optional[Dict]:
    """单条调用兼容入口，复用批量评分读取与历史分数补算逻辑。"""
    if submission.question is None:
        return None
    return visible_scores(db, [submission]).get(submission.id)


def _commit_score_backfills(db: Session) -> None:
    """把同一报告请求补算的历史分数集中提交一次。"""
    if not any(isinstance(item, SubmissionScore) for item in db.new):
        return
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = expire_on_commit


def visible_scores(
    db: Session,
    submissions: List[Submission],
    *,
    commit: bool = True,
) -> Dict[int, Dict]:
    """单次读取一页的成绩与评分配置；缺失的历史成绩按旧逻辑补算。"""
    question_data = {
        submission.id: (
            submission.question.id,
            submission.question.assignment_id,
        )
        for submission in submissions
        if submission.question is not None
    }
    valid = [submission for submission in submissions if submission.id in question_data]
    if not valid:
        return {}

    submission_ids = [submission.id for submission in valid]
    assignment_ids = {question_data[submission.id][1] for submission in valid}
    question_counts = (
        db.query(
            Question.assignment_id.label("assignment_id"),
            func.count(Question.id).label("question_count"),
        )
        .filter(Question.assignment_id.in_(assignment_ids))
        .group_by(Question.assignment_id)
        .subquery()
    )
    score_rows = (
        db.query(
            Submission.id.label("submission_id"),
            SubmissionScore.submission_id.label("score_submission_id"),
            SubmissionScore.final_score,
            SubmissionScore.ai_score,
            AssignmentScoring.total_score,
            QuestionWeight.weight_pct,
            question_counts.c.question_count,
        )
        .select_from(Submission)
        .join(Question, Question.id == Submission.question_id)
        .outerjoin(
            SubmissionScore,
            SubmissionScore.submission_id == Submission.id,
        )
        .outerjoin(
            AssignmentScoring,
            AssignmentScoring.assignment_id == Question.assignment_id,
        )
        .outerjoin(QuestionWeight, QuestionWeight.question_id == Question.id)
        .outerjoin(
            question_counts,
            question_counts.c.assignment_id == Question.assignment_id,
        )
        .filter(Submission.id.in_(submission_ids))
        .all()
    )
    score_values = {}
    max_scores = {}
    for row in score_rows:
        question_count = int(row.question_count or 0)
        total_score = float(row.total_score) if row.total_score else DEFAULT_TOTAL
        if row.weight_pct is not None:
            weight_pct = float(row.weight_pct)
        elif question_count:
            weight_pct = 100.0 / question_count
        else:
            weight_pct = 100.0
        max_scores[row.submission_id] = round(total_score * weight_pct / 100.0, 1)
        if row.score_submission_id is not None:
            score_values[row.submission_id] = (
                float(row.final_score)
                if row.final_score is not None else float(row.ai_score)
            )

    # 历史记录可能缺少分数行：批量读取步骤、按统一公式补分并一次写回。
    missing = [submission for submission in valid if submission.id not in score_values]
    result = {}
    if missing:
        missing_ids = [submission.id for submission in missing]
        step_counts_by_submission = {}
        for submission_id, status in db.query(Step.submission_id, Step.status).filter(
            Step.submission_id.in_(missing_ids),
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).all():
            counts = step_counts_by_submission.setdefault(submission_id, [0, 0])
            counts[1] += 1
            if status == "ok":
                counts[0] += 1

        rows_to_create = []
        for submission in missing:
            correct, total = step_counts_by_submission.get(submission.id, (0, 0))
            ai_score = round(
                max_scores[submission.id] * (correct / total if total else 0.0), 1
            )
            result[submission.id] = {
                "score": ai_score,
                "max_score": max_scores[submission.id],
            }
            rows_to_create.append(SubmissionScore(
                submission_id=submission.id,
                ai_score=ai_score,
            ))

        db.add_all(rows_to_create)
        if commit:
            _commit_score_backfills(db)

    for submission in valid:
        score = score_values.get(submission.id)
        if score is None:
            continue
        result[submission.id] = {
            "score": score,
            "max_score": max_scores[submission.id],
        }
    return result


def finalize_on_approve_many(
    db: Session, submissions: List[Submission], teacher,
) -> None:
    """批量落定通过审核的最终分，复用可见分批量补算旧记录。"""
    unique_submissions = {
        submission.id: submission
        for submission in submissions
        if submission.id is not None
    }
    if not unique_submissions:
        return

    items = list(unique_submissions.values())
    # visible_scores 限定每批大小，避免 SQLite 绑定参数上限；缺失的历史成绩
    # 会按统一规则批量补算并写入，已有教师最终分仍由下面的逻辑保留。
    for start in range(0, len(items), 300):
        visible_scores(db, items[start:start + 300], commit=False)

    scores_by_submission = {}
    submission_ids = list(unique_submissions)
    for start in range(0, len(submission_ids), 500):
        scores_by_submission.update({
            row.submission_id: row
            for row in db.query(SubmissionScore).filter(
                SubmissionScore.submission_id.in_(submission_ids[start:start + 500])
            ).all()
        })

    for submission_id, submission in unique_submissions.items():
        row = scores_by_submission.get(submission_id)
        if row is None:
            # 没有关联题目的历史异常记录无法由 visible_scores 处理；保持单条
            # finalize_on_approve 的满分为 0 口径，并仍然落定最终分。
            info = compute_ai_score(db, submission)
            row = SubmissionScore(
                submission_id=submission_id,
                ai_score=info["ai_score"],
            )
            db.add(row)
            scores_by_submission[submission_id] = row
        if row.final_score is None:
            row.final_score = row.ai_score
            row.updated_by = teacher.id
        row.updated_at = datetime.now()


def assignment_progress(
    db: Session,
    student_id: int,
    assignment_id: int,
    *,
    current_submission: Optional[Submission] = None,
    include_pending: bool = False,
) -> Dict:
    """一份作业的累计得分：每题取最新提交分求和，分母是作业总分。
    默认排除待审核记录；批改详情可包含待审 AI 分供学生即时查看。
    可选返回当前提交的成绩，供诊断页与作业累计分共用同一批成绩读取。"""
    from . import reviews as review_svc

    total_score_query = (
        db.query(AssignmentScoring.total_score)
        .filter(AssignmentScoring.assignment_id == assignment_id)
        .scalar_subquery()
    )
    latest_query = (
        db.query(
            Submission.id.label("submission_id"),
            func.row_number().over(
                partition_by=Submission.question_id,
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        )
        .join(Question, Submission.question_id == Question.id)
        .filter(
            Submission.student_id == student_id,
            Question.assignment_id == assignment_id,
            Submission.status == "graded",
        )
    )
    if not include_pending:
        latest_query = latest_query.outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        ).filter(
            func.coalesce(SubmissionReview.status, review_svc.APPROVED)
            != review_svc.PENDING,
        )
    latest_visible = latest_query.subquery()
    question_load = joinedload(Submission.question).load_only(
        Question.id, Question.assignment_id,
    )
    submission_rows = (
        db.query(Submission, total_score_query.label("assignment_total"))
        .join(latest_visible, latest_visible.c.submission_id == Submission.id)
        .options(
            load_only(Submission.id, Submission.question_id, Submission.submitted_at),
            question_load,
        )
        .filter(latest_visible.c.rank == 1)
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    if submission_rows:
        configured_total = submission_rows[0][1]
        total = float(configured_total) if configured_total else DEFAULT_TOTAL
        subs = [row[0] for row in submission_rows]
    else:
        total = assignment_total(db, assignment_id)
        subs = []
    if not subs and current_submission is None:
        return {"assignment_score": 0.0, "assignment_total": total}

    score_submissions = list(subs)
    if (
        current_submission is not None
        and all(item.id != current_submission.id for item in score_submissions)
    ):
        # 打开较早的提交详情时，它未必属于每题最新提交；仍需给详情返回本次成绩，
        # 但不能把它加入累计分的求和集合。
        score_submissions.append(current_submission)
    scores_by_submission = {}
    for start in range(0, len(score_submissions), 300):
        scores_by_submission.update(
            visible_scores(
                db, score_submissions[start:start + 300], commit=False
            )
        )
    _commit_score_backfills(db)

    latest: Dict[int, float] = {}
    for sub in subs:
        score_info = scores_by_submission.get(sub.id)
        if score_info is not None:
            latest[sub.question_id] = float(score_info["score"])
    result = {
        "assignment_score": round(sum(latest.values()), 1),
        "assignment_total": total,
    }
    if current_submission is not None:
        result["current_score"] = scores_by_submission.get(current_submission.id)
    return result


def score_detail_for_teacher(
    db: Session,
    submission: Submission,
    steps: Optional[List[Step]] = None,
) -> Dict:
    """审核详情用：满分、AI 分、最终分与步骤明细（老师据此决定是否改分）。"""
    info = compute_ai_score(db, submission, steps)
    row = get_score_row(db, submission.id)
    return {
        "question_max": info["max_score"],
        "ai_score": row.ai_score if row else info["ai_score"],
        "final_score": row.final_score if row else None,
        "ok_steps": info["ok_steps"],
        "total_steps": info["total_steps"],
    }


# ---------------------------------------------------------------- 报告成绩分析

def student_score_report(db: Session, student) -> Dict:
    """学习报告的成绩分析（只统计学生可见口径：审核已通过且有分的提交）：
    按作业聚合——每题取最新一次已通过提交的最终分求和；再算学科/总体平均得分率。
    在数据库中筛选每题最新可见提交，避免加载整段重复提交历史。"""
    from . import reviews as review_svc

    latest_visible = (
        db.query(
            Submission.id.label("submission_id"),
            func.row_number().over(
                partition_by=Submission.question_id,
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        )
        .join(Question, Question.id == Submission.question_id)
        .outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        )
        .filter(
            Submission.student_id == student.id,
            Submission.status == "graded",
            func.coalesce(SubmissionReview.status, review_svc.APPROVED)
            != review_svc.PENDING,
        )
        .subquery()
    )
    question_load = joinedload(Submission.question).load_only(
        Question.id, Question.assignment_id, Question.subject,
    ).joinedload(Question.assignment).load_only(Assignment.id, Assignment.title)
    subs = (
        db.query(Submission)
        .join(latest_visible, latest_visible.c.submission_id == Submission.id)
        .options(
            load_only(Submission.id, Submission.question_id, Submission.submitted_at),
            question_load,
        )
        .filter(latest_visible.c.rank == 1)
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    scores_by_submission = {}
    for start in range(0, len(subs), 300):
        scores_by_submission.update(
            visible_scores(db, subs[start:start + 300], commit=False)
        )
    _commit_score_backfills(db)
    # assignment_id -> {question_id: (submitted_at, final, max)}，后写覆盖 = 取最新一次
    per_assignment: Dict[int, Dict[int, Tuple]] = {}
    meta: Dict[int, Dict] = {}
    for sub in subs:
        score_info = scores_by_submission.get(sub.id)
        if score_info is None:
            continue
        q = sub.question
        per_assignment.setdefault(q.assignment_id, {})[q.id] = (
            sub.submitted_at, score_info["score"], score_info["max_score"],
        )
        if q.assignment_id not in meta:
            assignment = q.assignment
            meta[q.assignment_id] = {
                "title": assignment.title if assignment else "",
                "subject": q.subject,
            }
    items = []
    for aid, by_q in per_assignment.items():
        score = round(sum(v[1] for v in by_q.values()), 1)
        max_score = round(sum(v[2] for v in by_q.values()), 1)
        date = max(v[0] for v in by_q.values())
        items.append({
            "assignment_id": aid,
            "assignment_title": meta[aid]["title"],
            "subject": meta[aid]["subject"],
            "date": date,
            "score": score,
            "max_score": max_score,
            "rate": round(score / max_score, 4) if max_score else 0.0,
        })
    items.sort(key=lambda x: (x["date"], x["assignment_id"]))
    by_subject: Dict[str, List[float]] = {}
    for it in items:
        by_subject.setdefault(it["subject"], []).append(it["rate"])
    subjects = [
        {
            "subject": subj,
            "avg_rate": round(sum(rates) / len(rates), 4),
            "assignment_count": len(rates),
        }
        for subj, rates in sorted(by_subject.items())
    ]
    overall = (
        round(sum(it["rate"] for it in items) / len(items), 4) if items else None
    )
    return {"items": items, "subjects": subjects, "overall_avg_rate": overall}
