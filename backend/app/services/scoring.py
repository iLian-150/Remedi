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
# 分数跟着审核走：批改落库时只写 ai_score；教师审核通过时落定 final_score
# （老师改分则用老师的分，不改 = ai_score）。学生侧只在审核通过后才给分。
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
                           weights: List[Tuple[int, Optional[float]]]) -> None:
    """发布作业时落库分值配置（调用方负责 commit）：
    total_score 为 None 时不写总分行（走默认 100）；weights 里 pct 为 None 的题不写行（走均分）。"""
    if total_score is not None:
        row = db.query(AssignmentScoring).filter(
            AssignmentScoring.assignment_id == assignment_id
        ).first()
        if row is None:
            db.add(AssignmentScoring(assignment_id=assignment_id,
                                     total_score=float(total_score)))
        else:
            row.total_score = float(total_score)
    for question_id, pct in weights:
        if pct is None:
            continue
        row = db.query(QuestionWeight).filter(
            QuestionWeight.question_id == question_id
        ).first()
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
    db.commit()
    db.refresh(row)
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
                        final_score: Optional[float] = None) -> SubmissionScore:
    """教师审核通过时落定最终分：老师给了分就用老师的（调用方已做 0~满分校验），
    没给则 final = ai。已有 final 不覆盖老师先前定的分（除非本次显式给了新分）。"""
    row = ensure_score(db, submission)
    if final_score is not None:
        row.final_score = round(float(final_score), 1)
        row.updated_by = teacher.id
    elif row.final_score is None:
        row.final_score = row.ai_score
        row.updated_by = teacher.id
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return row


def visible_score(db: Session, submission: Submission) -> Optional[Dict]:
    """学生侧可见分（调用方须先确认审核已通过）：{score, max_score}。
    score 取 final（未落定则回退 ai，兼容无审核行的历史提交）。无分数行且
    算不出（题目已删等）时返回 None。"""
    question = submission.question
    if question is None:
        return None
    row = ensure_score(db, submission)
    score = row.final_score if row.final_score is not None else row.ai_score
    return {"score": float(score), "max_score": question_max_score(db, question)}


def visible_scores(db: Session, submissions: List[Submission]) -> Dict[int, Dict]:
    """批量读取一页已审核提交的可见成绩，缺失的历史成绩按旧逻辑补算。"""
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
    question_ids = {question_data[submission.id][0] for submission in valid}
    assignment_ids = {question_data[submission.id][1] for submission in valid}
    score_values = {
        row.submission_id: (
            float(row.final_score) if row.final_score is not None else float(row.ai_score)
        )
        for row in db.query(SubmissionScore).filter(
            SubmissionScore.submission_id.in_(submission_ids)
        ).all()
    }

    total_scores = {
        row.assignment_id: float(row.total_score) if row.total_score else DEFAULT_TOTAL
        for row in db.query(AssignmentScoring).filter(
            AssignmentScoring.assignment_id.in_(assignment_ids)
        ).all()
    }
    weights = {
        row.question_id: float(row.weight_pct)
        for row in db.query(QuestionWeight).filter(
            QuestionWeight.question_id.in_(question_ids)
        ).all()
    }
    question_counts = dict(
        db.query(Question.assignment_id, func.count(Question.id))
        .filter(Question.assignment_id.in_(assignment_ids))
        .group_by(Question.assignment_id)
        .all()
    )
    max_scores = {}
    for submission in valid:
        question_id, assignment_id = question_data[submission.id]
        question_count = question_counts.get(assignment_id, 0)
        weight_pct = weights.get(
            question_id, 100.0 / question_count if question_count else 100.0
        )
        max_scores[submission.id] = round(
            total_scores.get(assignment_id, DEFAULT_TOTAL) * weight_pct / 100.0,
            1,
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

        expire_on_commit = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.add_all(rows_to_create)
            db.commit()
        finally:
            db.expire_on_commit = expire_on_commit

    for submission in valid:
        score = score_values.get(submission.id)
        if score is None:
            continue
        result[submission.id] = {
            "score": score,
            "max_score": max_scores[submission.id],
        }
    return result


def assignment_progress(db: Session, student_id: int, assignment_id: int) -> Dict:
    """一份作业的累计得分（成绩单用）：每题取最新一次已通过提交的最终分求和，
    分母是作业总分。只算学生可见口径（待审核的不计）。"""
    from . import reviews as review_svc

    total = assignment_total(db, assignment_id)
    question_load = joinedload(Submission.question).load_only(
        Question.id, Question.assignment_id,
    )
    subs = (
        db.query(Submission)
        .join(Question, Submission.question_id == Question.id)
        .options(
            load_only(Submission.id, Submission.question_id, Submission.submitted_at),
            question_load,
        )
        .filter(Submission.student_id == student_id,
                Question.assignment_id == assignment_id,
                Submission.status == "graded")
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    if not subs:
        return {"assignment_score": 0.0, "assignment_total": total}

    pending = review_svc.pending_submission_ids(db, student_id)
    visible_subs = [sub for sub in subs if sub.id not in pending]
    scores_by_submission = {}
    for start in range(0, len(visible_subs), 300):
        scores_by_submission.update(
            visible_scores(db, visible_subs[start:start + 300])
        )

    latest: Dict[int, float] = {}
    for sub in visible_subs:
        score_info = scores_by_submission.get(sub.id)
        if score_info is not None:
            latest[sub.question_id] = float(score_info["score"])
    return {
        "assignment_score": round(sum(latest.values()), 1),
        "assignment_total": total,
    }


def score_detail_for_teacher(db: Session, submission: Submission) -> Dict:
    """审核详情用：满分、AI 分、最终分与步骤明细（老师据此决定是否改分）。"""
    info = compute_ai_score(db, submission)
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
    按作业聚合——每题取最新一次已通过提交的最终分求和；再算学科/总体平均得分率。"""
    from . import reviews as review_svc

    question_load = joinedload(Submission.question).load_only(
        Question.id, Question.assignment_id, Question.subject,
    ).joinedload(Question.assignment).load_only(Assignment.id, Assignment.title)
    subs = (
        db.query(Submission)
        .options(
            load_only(Submission.id, Submission.question_id, Submission.submitted_at),
            question_load,
        )
        .filter(Submission.student_id == student.id, Submission.status == "graded")
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    pending = review_svc.pending_submission_ids(db, student.id)
    visible_subs = [
        sub for sub in subs
        if sub.id not in pending and sub.question is not None
    ]
    scores_by_submission = {}
    for start in range(0, len(visible_subs), 300):
        scores_by_submission.update(
            visible_scores(db, visible_subs[start:start + 300])
        )
    # assignment_id -> {question_id: (submitted_at, final, max)}，后写覆盖 = 取最新一次
    per_assignment: Dict[int, Dict[int, Tuple]] = {}
    meta: Dict[int, Dict] = {}
    for sub in visible_subs:
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
