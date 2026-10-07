# 教师 Agent 工具集：全部复用 services/stats.py 与 services/teacher_stats.py 的聚合。
# 教师身份（db 会话 + teacher 对象）以闭包注入，模型无法传 user_id。
# 返回值是给模型看的紧凑文本摘要，不塞原始 JSON；学生 Agent 的工具在 tools.py，两边隔离。
from typing import List

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from ..models import User
from ..services.stats import class_repair_rate, knowledge_point_ranking, student_profile
from ..services.teacher_stats import (
    assignment_status,
    class_overview,
    find_assignment_by_hint,
    latest_assignment,
    uncorrected_overview,
)


def overview_to_text(overview: dict) -> str:
    return (
        f"班级共有学生 {overview['student_count']} 人，已发布作业 {overview['assignment_count']} 份，"
        f"累计提交 {overview['submission_count']} 次，累计诊断出错误 {overview['error_count']} 处。"
    )


def assignment_status_to_text(st: dict) -> str:
    lines = [
        f"《{st['title']}》共 {st['question_count']} 道题，班级 {st['student_total']} 名学生：",
        f"已全部完成 {len(st['done_all'])} 人"
        + (f"：{'、'.join(st['done_all'])}" if st["done_all"] else "。"),
    ]
    if st["partial"]:
        desc = "、".join(f"{p['name']}（已交 {p['done']}/{p['total']} 题）" for p in st["partial"])
        lines.append(f"部分完成 {len(st['partial'])} 人：{desc}。")
    if st["none"]:
        lines.append(f"完全没交 {len(st['none'])} 人：{'、'.join(st['none'])}。")
    if not st["partial"] and not st["none"]:
        lines.append("全班都已完成这份作业。")
    return "\n".join(lines)


def ranking_to_text(items: List[dict]) -> str:
    if not items:
        return "目前还没有错题数据，暂时排不出知识点错误率。"
    lines = ["知识点错误率排行（从高到低）："]
    for it in items:
        lines.append(
            f"- 「{it['knowledge_point']}」：错误率 {round(it['error_rate'] * 100)}%"
            f"（提交 {it['submissions']} 次、出错 {it['errors']} 次）。"
        )
    return "\n".join(lines)


def repair_rate_to_text(data: dict) -> str:
    lines = [
        f"班级知识修复率 {round(data['class_repair_rate'] * 100)}%："
        f"出过错的（学生×知识点）共 {data['total_knowledge_point_pairs']} 组，"
        f"已修复 {data['fixed_knowledge_point_pairs']} 组，涉及 {data['students_with_errors']} 名学生。"
        "（口径：错题订正正确后再做对一道同知识点变式题，才算已修复。）"
    ]
    for kp in data["knowledge_points"]:
        lines.append(
            f"- 「{kp['knowledge_point']}」：修复率 {round(kp['repair_rate'] * 100)}%"
            f"（{kp['students_fixed']}/{kp['students_errored']} 名学生已修复）。"
        )
    return "\n".join(lines)


def uncorrected_to_text(rows: List[dict]) -> str:
    if not rows:
        return "所有学生的错题都已订正完成，没有积压。"
    lines = ["订正还没完成的学生："]
    for r in rows:
        kps = "、".join(r["knowledge_points"])
        lines.append(f"- {r['student_name']}：还有 {r['uncorrected_count']} 处错题没订正（涉及知识点：{kps}）。")
    return "\n".join(lines)


def profile_to_text(profile: dict) -> str:
    st = profile["student"]
    lines = [f"学生 {st['name']} 的学习画像摘要："]
    kps = profile.get("knowledge_points", [])
    if kps:
        worst = kps[0]
        lines.append(
            f"最需要关注的知识点是「{worst['knowledge_point']}」：提交 {worst['attempts']} 次、"
            f"出错 {worst['errors']} 次，错误率 {round(worst['error_rate'] * 100)}%。"
        )
        rest = "、".join(
            f"「{k['knowledge_point']}」错误率 {round(k['error_rate'] * 100)}%" for k in kps[1:4]
        )
        if rest:
            lines.append(f"其他知识点：{rest}。")
    else:
        lines.append("暂时没有作答记录。")
    stubborn = profile.get("stubborn_errors", [])
    if stubborn:
        names = "、".join(sorted({e['knowledge_point'] for e in stubborn}))
        lines.append(f"有反复出错的记录，涉及知识点：{names}。")
    suggestion = profile.get("suggestion")
    if suggestion:
        lines.append(f"教学建议：{suggestion}")
    return "\n".join(lines)


def resolve_assignment(db: Session, hint: str):
    """工具/Mock 共用：按标题片段找作业；找不到且给了片段返回 (None, False)，
    没给片段时回退最近一份并标记 fallback=True。"""
    target = find_assignment_by_hint(db, hint) if hint else None
    if target:
        return target, False
    if hint:
        return None, False
    return latest_assignment(db), True


def build_teacher_tools(db: Session, teacher: User) -> list:
    """按当前教师构造工具列表（身份闭包注入）。"""

    @tool
    def get_class_overview() -> str:
        """查询班级总览：学生人数、已发布作业份数、累计提交次数与累计错误数。老师问"班级整体情况""多少人交了作业"时调用。"""
        return overview_to_text(class_overview(db))

    @tool
    def get_assignment_status(assignment_hint: str) -> str:
        """查询某份作业的提交情况：已全部完成、部分完成、完全没交的学生名单。参数 assignment_hint 是作业标题或标题中的关键词，例如「第一周」；不知道具体作业时传空字符串，默认查最近发布的一份。"""
        target, fallback = resolve_assignment(db, assignment_hint)
        if target is None:
            return "没有找到这份作业，请确认作业标题，或者换一份作业问我。"
        text = assignment_status_to_text(assignment_status(db, target))
        if fallback:
            text = f"（按最近发布的一份作业统计）\n{text}"
        return text

    @tool
    def get_knowledge_point_ranking() -> str:
        """查询知识点错误率排行（从高到低），用于判断哪个知识点最严重、最需要优先讲解。"""
        return ranking_to_text(knowledge_point_ranking(db))

    @tool
    def get_class_repair_rate() -> str:
        """查询班级知识修复率：已修复的（学生×知识点）占出过错组合的比例，以及各知识点的修复率。口径：订正正确后再做对一道同知识点变式题才算已修复。"""
        return repair_rate_to_text(class_repair_rate(db))

    @tool
    def get_uncorrected_students() -> str:
        """查询订正还没完成的学生：每人还有几处错题没订正、涉及哪些知识点。"""
        return uncorrected_to_text(uncorrected_overview(db))

    @tool
    def get_student_profile(student_name: str) -> str:
        """查询某个学生的学习画像摘要：各知识点错误率、反复出错的知识点与教学建议。参数 student_name 是学生姓名，例如「林小夏」。"""
        name = (student_name or "").strip()
        st = db.query(User).filter(User.name == name, User.role == "student").first()
        if st is None:
            candidates = db.query(User).filter(User.role == "student").all()
            st = next((c for c in candidates if name and (name in c.name or c.name in name)), None)
        if st is None:
            return f"没有找到学生「{student_name}」，请确认姓名。"
        return profile_to_text(student_profile(db, st))

    return [
        get_class_overview,
        get_assignment_status,
        get_knowledge_point_ranking,
        get_class_repair_rate,
        get_uncorrected_students,
        get_student_profile,
    ]
