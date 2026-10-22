# 教师 Agent 工具集：全部复用 services/stats.py 与 services/teacher_stats.py 的聚合。
# 教师身份（db 会话 + teacher 对象）以闭包注入，模型无法传 user_id。
# 返回值是给模型看的紧凑文本摘要，不塞原始 JSON；学生 Agent 的工具在 tools.py，两边隔离。
from typing import List

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from ..models import TeacherSubject, User
from ..services.stats import class_repair_rate, knowledge_point_ranking, student_profile, top_error_questions
from ..services.suggestions import build_teaching_suggestions
from ..services.teacher_stats import (
    assignment_status,
    class_overview,
    find_assignment_by_hint,
    latest_assignment,
    uncorrected_overview,
)
from ..services.teacher_scope import teacher_assignment_ids, teacher_student_ids


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


def profile_to_text(profile: dict, include_student_no: bool = False) -> str:
    st = profile["student"]
    student_label = f"学生 {st['name']}"
    if include_student_no:
        student_label += f"（学号：{st.get('student_no') or '未登记'}）"
    lines = [f"{student_label} 的学习画像摘要："]
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


def suggestions_to_text(items: List[dict]) -> str:
    if not items:
        return "目前还没有生成教学建议：班级数据还不够，或各知识点修复情况良好，可以先问我知识点错误率排行。"
    lines = ["根据班级的修复率、错误率、顽固错题与成绩数据，给你这几条教学建议："]
    for i, s in enumerate(items, 1):
        lines.append(f"{i}. {s['title']}——{s['evidence']}。建议：{s['action']}")
    return "\n".join(lines)


def _teacher_scope(db: Session, teacher: User) -> tuple[list[int], list[int]]:
    assignment_ids = [row[0] for row in teacher_assignment_ids(db, teacher).all()]
    student_ids = [row[0] for row in teacher_student_ids(db, teacher).all()]
    return assignment_ids, student_ids


def resolve_assignment(db: Session, hint: str, assignment_ids=None):
    """工具/Mock 共用：按标题片段找作业；找不到且给了片段返回 (None, False)，
    没给片段时回退最近一份并标记 fallback=True。"""
    target = find_assignment_by_hint(db, hint, assignment_ids) if hint else None
    if target:
        return target, False
    if hint:
        return None, False
    return latest_assignment(db, assignment_ids), True


def build_teacher_tools(db: Session, teacher: User) -> list:
    """按当前教师构造工具列表（身份闭包注入）。"""
    assignment_ids, student_ids = _teacher_scope(db, teacher)
    teaching_subjects = {row[0] for row in db.query(TeacherSubject.subject).filter_by(teacher_id=teacher.id)}

    @tool
    def search_teaching_knowledge(query: str, subject: str = "") -> str:
        """检索本人任教学科的教材、讲义、例题与评分标准，供备课或学科答疑引用。query 为完整问题；subject 为 math/english/chinese/physics/chemistry/biology/history/geography/politics 或中文学科名。只有一门任教学科时可留空。班级统计仍使用统计工具。"""
        from .subjects import build_subject_context, detect_subject, mentions_subject

        requested_subject = subject if isinstance(subject, str) else ""
        target = detect_subject(query, requested_subject)
        if (
            target is None and not requested_subject.strip()
            and not mentions_subject(query) and len(teaching_subjects) == 1
        ):
            target = next(iter(teaching_subjects))
        if target is None:
            return "请先确认要检索哪一门任教学科的教学资料。"
        if target not in teaching_subjects:
            return "该学科不在你当前的任教范围，无法检索其教学资料。"
        if not query.strip():
            return "请提供具体的教学问题。"
        return build_subject_context(db, target, query[:2000], teacher_mode=True)

    @tool
    def get_class_overview() -> str:
        """查询班级总览：学生人数、已发布作业份数、累计提交次数与累计错误数。老师问"班级整体情况""多少人交了作业"时调用。"""
        return overview_to_text(class_overview(db, assignment_ids, student_ids))

    @tool
    def get_assignment_status(assignment_hint: str) -> str:
        """查询某份作业的提交情况：已全部完成、部分完成、完全没交的学生名单。参数 assignment_hint 是作业标题或标题中的关键词，例如「第一周」；不知道具体作业时传空字符串，默认查最近发布的一份。"""
        target, fallback = resolve_assignment(db, assignment_hint, assignment_ids)
        if target is None:
            return "没有找到这份作业，请确认作业标题，或者换一份作业问我。"
        # 作业进度只列出这份作业接收班级的学生；教师可能还任教其他班级。
        text = assignment_status_to_text(assignment_status(db, target, student_ids=student_ids))
        if fallback:
            text = f"（按最近发布的一份作业统计）\n{text}"
        return text

    @tool
    def get_knowledge_point_ranking() -> str:
        """查询知识点错误率排行（从高到低），用于判断哪个知识点最严重、最需要优先讲解。"""
        return ranking_to_text(knowledge_point_ranking(db, assignment_ids))

    @tool
    def get_class_repair_rate() -> str:
        """查询班级知识修复率：已修复的（学生×知识点）占出过错组合的比例，以及各知识点的修复率。口径：订正正确后再做对一道同知识点变式题才算已修复。"""
        return repair_rate_to_text(class_repair_rate(db, student_ids, assignment_ids))

    @tool
    def get_uncorrected_students() -> str:
        """查询订正还没完成的学生：每人还有几处错题没订正、涉及哪些知识点。"""
        return uncorrected_to_text(uncorrected_overview(db, assignment_ids, student_ids))

    @tool
    def get_teaching_suggestions() -> str:
        """查询教学建议：下节课建议重讲什么知识点、哪些知识点错误率需要预警、哪些学生需要分组辅导、哪份作业需要巩固练习。老师问"下节课讲什么""有什么教学建议""备课重点"时调用。"""
        try:
            scoped_stats = {
                "repair_rate": class_repair_rate(db, student_ids, assignment_ids),
                "knowledge_points": knowledge_point_ranking(db, assignment_ids),
                "top_questions": top_error_questions(db, 50, assignment_ids),
                "assignment_ids": assignment_ids,
            }
            return suggestions_to_text(build_teaching_suggestions(db, scoped_stats))
        except Exception:
            return "教学建议暂时生成失败，请稍后再试；你也可以先问我知识点错误率排行或班级知识修复率。"

    @tool
    def get_student_profile(
        student_name: str, student_no: str = "", include_student_no: bool = False,
    ) -> str:
        """查询任课班级中的某个学生画像。姓名可能重复；同名时请传学号。老师明确询问学号时设 include_student_no=True，否则保持默认以减少学号展示。"""
        name = (student_name or "").strip()
        query = db.query(User).filter(User.role == "student", User.id.in_(student_ids))
        if student_no.strip():
            st = query.filter(User.student_no == student_no.strip()).first()
        else:
            candidates = query.filter(User.name.contains(name)).all() if name else []
            if len(candidates) > 1:
                numbers = "、".join(item.student_no or "无学号" for item in candidates[:8])
                return f"找到多个同名学生，请用学号进一步确认：{numbers}。"
            st = candidates[0] if candidates else None
        if st is None:
            return f"在你任课的班级中没有找到学生「{student_name}」，请检查姓名和学号。"
        return profile_to_text(
            student_profile(db, st, assignment_ids=assignment_ids),
            include_student_no=include_student_no,
        )

    return [
        search_teaching_knowledge,
        get_class_overview,
        get_assignment_status,
        get_knowledge_point_ranking,
        get_class_repair_rate,
        get_uncorrected_students,
        get_teaching_suggestions,
        get_student_profile,
    ]
