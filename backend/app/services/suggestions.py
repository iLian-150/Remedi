# 教学建议生成：只读现成统计（stats 的修复率/错误率排行/高频错题 + scoring 的成绩聚合），
# 纯规则模板拼装，不调 LLM、毫秒级返回。任何一项统计异常只跳过对应规则，绝不抛 500。
# 规则（按严重度 reteach > stubborn_group > high_error > low_score 排序，最多 6 条）：
#   reteach        —— 知识点班级修复率 < 50% 且出错学生 ≥ 2：建议重讲
#   stubborn_group —— 某知识点有 ≥ 2 名学生存在顽固（is_stubborn）错题：分组辅导
#   high_error     —— 知识点错误率 ≥ 50%（未被 reteach 覆盖）：高错误率预警
#   low_score      —— 某份作业全班平均得分率 < 60%（已批改 ≥ 2 份）：巩固练习
import logging
from typing import Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    AssignmentScoring,
    Error,
    Question,
    QuestionWeight,
    Step,
    Submission,
    SubmissionReview,
    SubmissionScore,
)
from .stats import class_repair_rate, knowledge_point_ranking, top_error_questions

_KIND_ORDER = {"reteach": 0, "stubborn_group": 1, "high_error": 2, "low_score": 3}
_MAX_SUGGESTIONS = 6
logger = logging.getLogger(__name__)


def _pct(rate: Optional[float]) -> int:
    return round((rate or 0.0) * 100)


def build_teaching_suggestions(
    db: Session,
    precomputed_stats: Optional[Dict] = None,
) -> List[Dict]:
    """生成教学建议列表。数据为空返回 []；统计异常逐项收敛为跳过。"""
    repair_map: Dict[str, Dict] = {}
    ranking_map: Dict[str, Dict] = {}
    samples_map: Dict[str, List[str]] = {}
    try:
        repair_data = (
            precomputed_stats.get("repair_rate") or {}
            if precomputed_stats is not None else class_repair_rate(db)
        )
        for kp in repair_data.get("knowledge_points", []):
            key = kp["knowledge_point"]
            combined = repair_map.setdefault(key, {
                "knowledge_point": key,
                "students_errored": 0,
                "students_fixed": 0,
                "repair_rate": 0.0,
            })
            combined["students_errored"] += kp["students_errored"]
            combined["students_fixed"] += kp["students_fixed"]
            combined["repair_rate"] = round(
                combined["students_fixed"] / combined["students_errored"], 3,
            ) if combined["students_errored"] else 0.0
    except Exception:
        repair_map = {}
    try:
        ranking_data = (
            precomputed_stats.get("knowledge_points", [])
            if precomputed_stats is not None else knowledge_point_ranking(db)
        )
        for it in ranking_data:
            ranking_map[it["knowledge_point"]] = it
    except Exception:
        ranking_map = {}
    try:
        question_data = (
            precomputed_stats.get("top_questions", [])
            if precomputed_stats is not None else top_error_questions(db, 50)
        )
        for q in question_data:
            bucket = samples_map.setdefault(q["knowledge_point"], [])
            if q.get("stem") and len(bucket) < 2:
                bucket.append(q["stem"])
    except Exception:
        samples_map = {}

    items: List[Dict] = []
    assignment_ids = (
        precomputed_stats.get("assignment_ids")
        if precomputed_stats is not None else None
    )
    student_ids = (
        precomputed_stats.get("student_ids")
        if precomputed_stats is not None else None
    )
    submission_ids = (
        precomputed_stats.get("submission_ids")
        if precomputed_stats is not None else None
    )

    # ---- reteach：修复率低且波及多名学生 ----
    reteach_kps = set()
    for kp_name, kp in repair_map.items():
        if kp["repair_rate"] < 0.5 and kp["students_errored"] >= 2:
            reteach_kps.add(kp_name)
            errors = ranking_map.get(kp_name, {}).get("errors")
            evidence = (
                f"全班 {kp['students_errored']} 人出错 · 修复率 {_pct(kp['repair_rate'])}%"
                + (f" · 累计错 {errors} 次" if errors is not None else "")
            )
            items.append({
                "kind": "reteach",
                "title": f"建议重讲：{kp_name}",
                "knowledge_point": kp_name,
                "evidence": evidence,
                "action": (
                    f"下节课用 10 分钟重讲「{kp_name}」的关键点，结合高频错题讲清最常见的错因，"
                    "课后用一道同知识点变式题当堂验证是否真懂。"
                ),
                "sample_questions": samples_map.get(kp_name, []),
                "_sort": (_KIND_ORDER["reteach"], kp["repair_rate"]),
            })

    # ---- stubborn_group：多名学生在同一知识点反复出错 ----
    try:
        stubborn_query = (
            db.query(
                Error.knowledge_point,
                func.count(func.distinct(Submission.student_id)).label("students"),
                func.count(Error.id).label("errors"),
            )
            .join(Submission, Error.submission_id == Submission.id)
            .join(Question, Question.id == Submission.question_id)
            .filter(Error.is_stubborn.is_(True))
        )
        if assignment_ids is not None:
            stubborn_query = stubborn_query.filter(Question.assignment_id.in_(assignment_ids))
        if student_ids is not None:
            stubborn_query = stubborn_query.filter(Submission.student_id.in_(student_ids))
        if submission_ids is not None:
            stubborn_query = stubborn_query.filter(Submission.id.in_(submission_ids))
        rows = stubborn_query.group_by(Error.knowledge_point).all()
    except Exception:
        rows = []
    for kp_name, students, errors in rows:
        if students < 2:
            continue
        repair_pct = _pct(repair_map.get(kp_name, {}).get("repair_rate"))
        items.append({
            "kind": "stubborn_group",
            "title": f"分组辅导：{kp_name}",
            "knowledge_point": kp_name,
            "evidence": f"{students} 名学生反复出错 · 顽固错题 {errors} 条 · 修复率 {repair_pct}%",
            "action": (
                f"把这 {students} 名学生拉一个小组辅导，逐个过一遍他们的错题步骤，"
                "定位各自卡住的那一步，再针对性补练。"
            ),
            "sample_questions": samples_map.get(kp_name, []),
            "_sort": (_KIND_ORDER["stubborn_group"], -students),
        })

    # ---- high_error：错误率高但未被 reteach 覆盖 ----
    for kp_name, it in ranking_map.items():
        if it["error_rate"] < 0.5 or kp_name in reteach_kps:
            continue
        repair = repair_map.get(kp_name, {})
        evidence = (
            f"错误率 {_pct(it['error_rate'])}%（提交 {it['submissions']} 次、出错 {it['errors']} 次）"
            f" · 全班 {repair.get('students_errored', 0)} 人出错 · 修复率 {_pct(repair.get('repair_rate'))}%"
        )
        items.append({
            "kind": "high_error",
            "title": f"高错误率预警：{kp_name}",
            "knowledge_point": kp_name,
            "evidence": evidence,
            "action": (
                f"在下一次作业讲评里优先讲「{kp_name}」，挑一道高频错题完整演示正确步骤，"
                "再让学生当堂订正。"
            ),
            "sample_questions": samples_map.get(kp_name, []),
            "_sort": (_KIND_ORDER["high_error"], -it["error_rate"]),
        })

    # ---- low_score：某份作业整体得分率偏低 ----
    try:
        from .scoring import DEFAULT_TOTAL

        question_counts = (
            db.query(
                Question.assignment_id.label("assignment_id"),
                func.count(Question.id).label("question_count"),
            )
            .group_by(Question.assignment_id)
            .subquery()
        )
        step_counts = (
            db.query(
                Step.submission_id.label("submission_id"),
                func.sum(case((Step.status == "ok", 1), else_=0)).label(
                    "correct_steps"
                ),
                func.count(Step.id).label("total_steps"),
            )
            .join(Submission, Submission.id == Step.submission_id)
            .filter(
                Submission.status == "graded",
                Step.seq >= 1,
                Step.status.in_(("ok", "error", "unparseable")),
            )
            .group_by(Step.submission_id)
            .subquery()
        )
        latest_graded = db.query(
            Submission.id.label("submission_id"),
            func.row_number().over(
                partition_by=(Submission.student_id, Submission.question_id),
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        ).join(
            Question, Question.id == Submission.question_id,
        ).outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        ).filter(
            Submission.status == "graded",
            func.coalesce(SubmissionReview.status, "approved") != "pending",
        )
        if assignment_ids is not None:
            latest_graded = latest_graded.filter(Question.assignment_id.in_(assignment_ids))
        if student_ids is not None:
            latest_graded = latest_graded.filter(Submission.student_id.in_(student_ids))
        if submission_ids is not None:
            latest_graded = latest_graded.filter(Submission.id.in_(submission_ids))
        latest_graded = latest_graded.subquery()

        score_rows = (
            db.query(Submission)
            .with_entities(
                Submission.id.label("submission_id"),
                Assignment.id.label("assignment_id"),
                Assignment.title.label("assignment_title"),
                SubmissionScore.submission_id.label("score_submission_id"),
                SubmissionScore.final_score.label("final_score"),
                SubmissionScore.ai_score.label("ai_score"),
                AssignmentScoring.total_score.label("assignment_total"),
                QuestionWeight.question_id.label("weight_question_id"),
                QuestionWeight.weight_pct.label("weight_pct"),
                question_counts.c.question_count,
                step_counts.c.correct_steps,
                step_counts.c.total_steps,
            )
            .join(Question, Question.id == Submission.question_id)
            .outerjoin(Assignment, Assignment.id == Question.assignment_id)
            .outerjoin(
                SubmissionScore,
                SubmissionScore.submission_id == Submission.id,
            )
            .outerjoin(
                AssignmentScoring,
                AssignmentScoring.assignment_id == Question.assignment_id,
            )
            .outerjoin(
                QuestionWeight,
                QuestionWeight.question_id == Question.id,
            )
            .outerjoin(
                question_counts,
                question_counts.c.assignment_id == Question.assignment_id,
            )
            .outerjoin(
                step_counts,
                step_counts.c.submission_id == Submission.id,
            )
            .join(
                latest_graded,
                latest_graded.c.submission_id == Submission.id,
            )
            .filter(latest_graded.c.rank == 1)
        )
        if assignment_ids is not None:
            score_rows = score_rows.filter(Assignment.id.in_(assignment_ids))
        if student_ids is not None:
            score_rows = score_rows.filter(Submission.student_id.in_(student_ids))
        if submission_ids is not None:
            score_rows = score_rows.filter(Submission.id.in_(submission_ids))
        per_assignment: Dict[int, tuple[str, int, float]] = {}
        created_missing_score = False
        for row in score_rows.yield_per(1000):
            assignment_total = (
                float(row.assignment_total)
                if row.assignment_total else DEFAULT_TOTAL
            )
            question_count = int(row.question_count or 0)
            weight_pct = (
                float(row.weight_pct)
                if row.weight_question_id is not None
                else 100.0 / question_count if question_count else 100.0
            )
            max_score = round(assignment_total * weight_pct / 100.0, 1)
            if row.score_submission_id is None:
                correct_steps = int(row.correct_steps or 0)
                total_steps = int(row.total_steps or 0)
                final = round(
                    max_score * (correct_steps / total_steps if total_steps else 0.0),
                    1,
                )
                # Keep the same legacy-score backfill performed by visible_scores,
                # but persist all missing rows with one commit after the scan.
                db.add(SubmissionScore(
                    submission_id=row.submission_id,
                    ai_score=final,
                ))
                created_missing_score = True
            else:
                final = float(
                    row.final_score
                    if row.final_score is not None else row.ai_score
                )
            if not max_score:
                continue
            title = row.assignment_title or "未命名作业"
            count, rate_sum = per_assignment.get(row.assignment_id, (title, 0, 0.0))[1:]
            per_assignment[row.assignment_id] = (
                title,
                count + 1,
                rate_sum + float(final) / float(max_score),
            )

        if created_missing_score:
            db.commit()
        for title, count, rate_sum in per_assignment.values():
            if count < 2:
                continue
            avg = rate_sum / count
            if avg >= 0.6:
                continue
            items.append({
                "kind": "low_score",
                "title": f"巩固练习：{title}",
                "knowledge_point": None,
                "evidence": f"《{title}》全班平均得分率 {_pct(avg)}%（{count} 份已批改提交）",
                "action": (
                    f"建议针对《{title}》的错题安排一次巩固练习，讲评后督促学生完成订正与二次验证。"
                ),
                "sample_questions": [],
                "_sort": (_KIND_ORDER["low_score"], avg),
            })
    except Exception:
        logger.exception("教学建议低分统计失败")

    items.sort(key=lambda x: x["_sort"])
    result = items[:_MAX_SUGGESTIONS]
    for it in result:
        it.pop("_sort", None)
    return result
