# 教学建议生成：只读现成统计（stats 的修复率/错误率排行/高频错题 + scoring 的成绩聚合），
# 纯规则模板拼装，不调 LLM、毫秒级返回。任何一项统计异常只跳过对应规则，绝不抛 500。
# 规则（按严重度 reteach > stubborn_group > high_error > low_score 排序，最多 6 条）：
#   reteach        —— 知识点班级修复率 < 50% 且出错学生 ≥ 2：建议重讲
#   stubborn_group —— 某知识点有 ≥ 2 名学生存在顽固（is_stubborn）错题：分组辅导
#   high_error     —— 知识点错误率 ≥ 50%（未被 reteach 覆盖）：高错误率预警
#   low_score      —— 某份作业全班平均得分率 < 60%（已批改 ≥ 2 份）：巩固练习
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Error, Question, Submission
from .stats import class_repair_rate, knowledge_point_ranking, top_error_questions

_KIND_ORDER = {"reteach": 0, "stubborn_group": 1, "high_error": 2, "low_score": 3}
_MAX_SUGGESTIONS = 6


def _pct(rate: Optional[float]) -> int:
    return round((rate or 0.0) * 100)


def build_teaching_suggestions(db: Session) -> List[Dict]:
    """生成教学建议列表。数据为空返回 []；统计异常逐项收敛为跳过。"""
    repair_map: Dict[str, Dict] = {}
    ranking_map: Dict[str, Dict] = {}
    samples_map: Dict[str, List[str]] = {}
    try:
        for kp in class_repair_rate(db).get("knowledge_points", []):
            repair_map[kp["knowledge_point"]] = kp
    except Exception:
        repair_map = {}
    try:
        for it in knowledge_point_ranking(db):
            ranking_map[it["knowledge_point"]] = it
    except Exception:
        ranking_map = {}
    try:
        for q in top_error_questions(db, 50):
            bucket = samples_map.setdefault(q["knowledge_point"], [])
            if q.get("stem") and len(bucket) < 2:
                bucket.append(q["stem"])
    except Exception:
        samples_map = {}

    items: List[Dict] = []

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
        rows = (
            db.query(
                Error.knowledge_point,
                func.count(func.distinct(Submission.student_id)).label("students"),
                func.count(Error.id).label("errors"),
            )
            .join(Submission, Error.submission_id == Submission.id)
            .filter(Error.is_stubborn.is_(True))
            .group_by(Error.knowledge_point)
            .all()
        )
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
        from .scoring import visible_scores

        per_assignment: Dict[str, List[float]] = {}
        subs = (
            db.query(Submission)
            .options(
                joinedload(Submission.question).joinedload(Question.assignment)
            )
            .filter(Submission.status == "graded")
            .all()
        )
        scores_by_submission = {}
        for start in range(0, len(subs), 300):
            scores_by_submission.update(
                visible_scores(db, subs[start:start + 300])
            )
        for sub in subs:
            question = sub.question
            score_info = scores_by_submission.get(sub.id)
            if question is None or score_info is None:
                continue
            final = score_info["score"]
            max_score = score_info["max_score"]
            if not max_score:
                continue
            title = question.assignment.title if question.assignment else "未命名作业"
            per_assignment.setdefault(title, []).append(float(final) / float(max_score))
        for title, rates in per_assignment.items():
            if len(rates) < 2:
                continue
            avg = sum(rates) / len(rates)
            if avg >= 0.6:
                continue
            items.append({
                "kind": "low_score",
                "title": f"巩固练习：{title}",
                "knowledge_point": None,
                "evidence": f"《{title}》全班平均得分率 {_pct(avg)}%（{len(rates)} 份已批改提交）",
                "action": (
                    f"建议针对《{title}》的错题安排一次巩固练习，讲评后督促学生完成订正与二次验证。"
                ),
                "sample_questions": [],
                "_sort": (_KIND_ORDER["low_score"], avg),
            })
    except Exception:
        pass

    items.sort(key=lambda x: x["_sort"])
    result = items[:_MAX_SUGGESTIONS]
    for it in result:
        it.pop("_sort", None)
    return result
