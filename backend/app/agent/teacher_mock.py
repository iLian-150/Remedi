# 教师 Agent 的 Mock 兜底回复：LLM_PROVIDER=mock、无凭证、或图调用异常时使用。
# 关键词路由到真实数据函数拼模板回复——数据是真的，只是话术是模板，永不编造。
from sqlalchemy.orm import Session

from ..models import User
from ..services.stats import class_repair_rate, knowledge_point_ranking, student_profile
from ..services.suggestions import build_teaching_suggestions
from ..services.teacher_stats import (
    assignment_status,
    class_overview,
    uncorrected_overview,
)
from .teacher_tools import (
    assignment_status_to_text,
    overview_to_text,
    profile_to_text,
    ranking_to_text,
    repair_rate_to_text,
    resolve_assignment,
    suggestions_to_text,
    uncorrected_to_text,
)

_SUGGESTION_KEYWORDS = ("教学建议", "建议", "下节课", "讲什么", "备课", "重点讲")
_REPAIR_KEYWORDS = ("修复率", "修复")
_RANKING_KEYWORDS = ("知识点", "错误率", "最严重", "最薄弱", "薄弱", "排行")
_CORRECTION_KEYWORDS = ("订正",)
_SUBMIT_KEYWORDS = ("没交", "未交", "还没交", "没做完", "提交情况", "交了", "提交了多少", "多少人交", "谁没")
_OVERVIEW_KEYWORDS = ("总览", "全班", "班级情况", "多少人", "多少学生", "整体")
_GREETING_KEYWORDS = ("你好", "您好", "hi", "hello", "在吗")


def _assignment_hint(db: Session, msg: str) -> str:
    """从消息里抽作业线索：优先《》内的标题，其次是与某份作业标题有交集的片段。"""
    if "《" in msg and "》" in msg:
        return msg.split("《", 1)[1].split("》", 1)[0]
    from ..models import Assignment

    for a in db.query(Assignment).all():
        if a.title in msg:
            return a.title
        # 标题里的显著片段（如「第一周」）出现在消息里也算命中
        for frag in (a.title[:3], a.title[:2]):
            if frag and frag in msg:
                return a.title
    return ""


def _mentioned_student(db: Session, msg: str):
    students = db.query(User).filter(User.role == "student").all()
    for st in students:
        if st.name and st.name in msg:
            return st
    return None


def teacher_mock_reply(db: Session, teacher: User, message: str) -> str:
    """规则回复入口：按关键词路由到真实数据模板，兜底给能力说明 + 总览数字。"""
    msg = (message or "").strip()

    # 0) 教学建议（要在"知识点/建议先讲"类问法之前判，意图最明确）
    if any(k in msg for k in _SUGGESTION_KEYWORDS):
        try:
            return suggestions_to_text(build_teaching_suggestions(db))
        except Exception:
            return "教学建议暂时生成失败，请稍后再试；你也可以先问我知识点错误率排行或班级知识修复率。"

    # 1) 班级知识修复率
    if any(k in msg for k in _REPAIR_KEYWORDS):
        return repair_rate_to_text(class_repair_rate(db))

    # 2) 订正未完成（要在"提交"之前判，"谁的订正还没完成"也含"还没"）
    if any(k in msg for k in _CORRECTION_KEYWORDS):
        return uncorrected_to_text(uncorrected_overview(db))

    # 3) 知识点错误率排行
    if any(k in msg for k in _RANKING_KEYWORDS):
        items = knowledge_point_ranking(db)
        text = ranking_to_text(items)
        if items:
            text += f"\n建议先讲排第一的「{items[0]['knowledge_point']}」，它的错误率最高。"
        return text

    # 4) 点名某个学生 → 画像摘要
    st = _mentioned_student(db, msg)
    if st is not None:
        return profile_to_text(student_profile(db, st))

    # 5) 某份作业的提交情况 / 谁还没交
    if any(k in msg for k in _SUBMIT_KEYWORDS):
        hint = _assignment_hint(db, msg)
        target, fallback = resolve_assignment(db, hint)
        if target is None:
            return "没有找到这份作业，请把作业标题发我（例如《第一周数学作业》），我再帮你查。"
        text = assignment_status_to_text(assignment_status(db, target))
        if fallback:
            text = "你没有指明哪份作业，我先按最近发布的一份统计：\n" + text
        return text

    # 6) 打招呼
    if any(k in msg.lower() for k in _GREETING_KEYWORDS):
        return (
            f"你好，{teacher.name}！我是你的班级数据助理。\n"
            + overview_to_text(class_overview(db))
            + "\n你可以问我：某份作业谁还没交、哪个知识点错误率最高、班级知识修复率、某个学生的情况。"
        )

    # 7) 班级总览
    if any(k in msg for k in _OVERVIEW_KEYWORDS):
        return overview_to_text(class_overview(db))

    # 8) 兜底：能力说明 + 真实总览（不编造任何名单与数字）
    return (
        "这个问题我暂时答不上来，我能查的是班级里的真实数据，你可以这样问我：\n"
        "「《作业名》谁还没交」「哪个知识点错误率最高」「班级知识修复率怎么样」「谁的订正还没完成」「某个学生最近学得怎么样」。\n"
        "先给你一个总览：\n" + overview_to_text(class_overview(db))
    )
