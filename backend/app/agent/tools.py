# Agent 工具集：三个工具全部复用 services/stats.py 的既有聚合函数。
# 学生身份（db 会话 + student 对象）在建工具时以闭包注入，模型无法传 user_id，
# 从根本上杜绝越权查询他人数据。工具返回值是给模型看的紧凑文本摘要，不塞原始 JSON。
from typing import List

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from ..models import User
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_report,
)

_STATUS_LABEL = {
    "pending": "待修复",
    "stubborn": "需要加固（反复出错）",
    "fixed": "已加固",
}


def _fmt_date(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def briefing_to_text(briefing: dict) -> str:
    """把 student_briefing 的结构化结果压成一段紧凑文本（工具与上下文注入共用）。"""
    lines = []
    pending = briefing.get("pending_assignments", [])
    if pending:
        desc = "；".join(
            f"《{p['title']}》（还剩 {p['remaining_count']} 题未做）" for p in pending
        )
        lines.append(f"未完成的作业 {len(pending)} 份：{desc}")
    else:
        lines.append("作业都已完成，没有未完成的作业。")
    corr_n = briefing.get("pending_corrections_count", 0)
    if corr_n:
        kps = "、".join(briefing.get("pending_corrections_knowledge_points", []))
        lines.append(f"有 {corr_n} 处错题还没订正，涉及知识点：{kps}。")
    weak = briefing.get("weak_points", [])
    if weak:
        lines.append(f"需要加固的知识点：{'、'.join(weak)}。")
    recent = briefing.get("recent_feedback")
    if recent:
        lines.append(f"最近动态：{recent}")
    return "\n".join(lines)


def report_to_text(report: List[dict]) -> str:
    """把 student_report 压成紧凑文本：按科目给提交/正确率，知识点按错误率列出。"""
    if not report:
        return "还没有任何作答记录，暂时没有学习报告数据。"
    lines = []
    for subj in report:
        lines.append(
            f"科目 {subj['subject']}：累计提交 {subj['submission_count']} 次，"
            f"正确率约 {round(subj['correct_rate'] * 100)}%，"
            f"待修复知识点 {subj['pending_fix_count']} 个，修复进度 {round(subj['fixed_ratio'] * 100)}%。"
        )
        for kp in subj["knowledge_points"]:
            lines.append(
                f"- 知识点「{kp['name']}」：提交 {kp['attempts']} 次、出错 {kp['error_count']} 次"
                f"（错误率 {round(kp['error_rate'] * 100)}%），状态：{_STATUS_LABEL.get(kp['status'], kp['status'])}"
                f"，最近出错 {_fmt_date(kp['last_error_at'])}。"
            )
        if not subj["knowledge_points"]:
            lines.append("- 暂无错题记录。")
    return "\n".join(lines)


def kp_errors_to_text(knowledge_point: str, items: List[dict]) -> str:
    """知识点错题时间线压成紧凑文本（最多 10 条）。"""
    if not items:
        return f"在「{knowledge_point}」下还没有错题记录。"
    lines = [f"「{knowledge_point}」的错题记录（共 {len(items)} 条，最近的在前）："]
    for it in items[:10]:
        seq = f"，第 {it['first_error_seq']} 步出错" if it.get("first_error_seq") is not None else ""
        corr = "已订正" if it.get("corrected") else "未订正"
        lines.append(
            f"- {_fmt_date(it['created_at'])} 《{it['assignment_title']}》{it['question_prompt']}"
            f"{seq}，问题类型：{it['error_type']}，{corr}。"
        )
    return "\n".join(lines)


def build_tools(db: Session, student: User) -> list:
    """按当前学生构造工具列表（身份闭包注入）。"""

    @tool
    def get_my_briefing() -> str:
        """查询学生当前的待办情况：未完成的作业、还没订正的错题数、需要加固的知识点。当学生问"我还有什么没做""作业做完了吗"之类的问题时调用。"""
        return briefing_to_text(student_briefing(db, student))

    @tool
    def get_my_report() -> str:
        """查询学生的学习报告摘要：各科目提交次数、正确率，以及每个知识点的错误率和状态（待修复/需要加固/已加固）。当学生问"我学得怎么样""哪个知识点最弱"时调用。"""
        return report_to_text(student_report(db, student))

    @tool
    def get_knowledge_point_errors(knowledge_point: str) -> str:
        """查询学生在某个知识点下的错题时间线。参数 knowledge_point 是知识点名称，例如「一元一次方程」。当学生问"我在某个知识点错过哪些题"时调用。"""
        items = knowledge_point_errors(db, student, knowledge_point)
        return kp_errors_to_text(knowledge_point, items)

    return [get_my_briefing, get_my_report, get_knowledge_point_errors]
