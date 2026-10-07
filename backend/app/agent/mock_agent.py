# Mock 兜底回复：LLM_PROVIDER=mock、无凭证、或图调用异常时使用。
# 关键词路由到真实数据函数（briefing / report / 错题时间线）拼模板回复——
# 回复里的数据是真的，只是话术是模板；纯数学闲聊给一条罐头讲解。
import re

from sqlalchemy.orm import Session
from sympy import Poly, simplify, solve

from ..models import User
from ..services.mathparse import extract_equation
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_report,
)
from .tools import briefing_to_text, kp_errors_to_text, report_to_text

_TODO_KEYWORDS = ("没做", "未完成", "待办", "没交", "还有哪些作业", "还有什么作业", "要做什么")
_WEAK_KEYWORDS = ("最弱", "薄弱", "最差", "需要加固", "掌握", "报告", "学得怎么样", "学习情况")
_GREETING_KEYWORDS = ("你好", "您好", "hi", "hello", "在吗", "早上好", "晚上好")

_CANNED_EXPLANATION = (
    "好问题，我们就拿「移项为什么要变号」来说。\n"
    "方程其实就是一架天平，等号两边要保持平衡。以 2x+3=7 为例，想把左边的 +3 拿走，"
    "就在等号两边同时减去 3：左边剩下 2x，右边变成 7-3，于是 2x=7-3。"
    "平时说的「移项变号」，就是这一步的简写：把一项移到等号另一边时，符号要反过来——"
    "加变减、减变加、乘变除、除变乘。\n"
    "记住一句话：移项不是搬家，是等号两边同时做同样的运算。\n"
    "（小提示：接入真实模型后可以自由问答，任何数学问题都可以接着聊；现在先用这条示例讲解陪你。）"
)


def _known_knowledge_points(db: Session, student: User) -> list:
    """该生出现过的知识点名称（报告里的 + 简报需加固的），用于错题问答的关键词匹配。"""
    names = []
    for subj in student_report(db, student, visible_only=True):
        for kp in subj["knowledge_points"]:
            if kp["name"] not in names:
                names.append(kp["name"])
    for kp in student_briefing(db, student, visible_only=True).get("weak_points", []):
        if kp not in names:
            names.append(kp)
    return names


def mock_reply(db: Session, student: User, message: str) -> str:
    """规则回复入口：按关键词路由到真实数据模板，兜底给罐头讲解。"""
    msg = (message or "").strip()

    # 图片题答疑在 Mock 模式下也根据识别出的方程给出对应结果，避免把固定示例
    # （2x+3=7）误套到学生上传的其他题目上。
    photo_question = re.search(r"识别出的题目：([^\n]+)", msg)
    if photo_question:
        stem = photo_question.group(1).strip()
        parsed = extract_equation(stem)
        if parsed and parsed.kind == "eq" and parsed.expr.free_symbols:
            try:
                symbol = sorted(parsed.expr.free_symbols, key=lambda item: str(item))[0]
                polynomial = Poly(simplify(parsed.expr.lhs - parsed.expr.rhs), symbol)
                if polynomial.degree() == 1:
                    coefficient = polynomial.coeff_monomial(symbol)
                    constant = polynomial.coeff_monomial(1)
                    answer = solve(parsed.expr, symbol)[0]
                    return (
                        f"题目是：{stem}\n"
                        f"把常数项移到等号另一边，得到 {coefficient}×{symbol}={-constant}；"
                        f"再两边同时除以 {coefficient}，所以 {symbol}={answer}。\n"
                        "关键是等号两边同时做相同的运算，等式才会保持平衡。"
                    )
            except Exception:
                pass
        return f"我先读到的题目是：{stem}\n先找出题目给出的条件和要求，再一步一步列式计算。你可以把题干文字发给我，我会继续讲具体步骤。"

    # 1) 待办类
    if any(k in msg for k in _TODO_KEYWORDS):
        briefing = student_briefing(db, student, visible_only=True)
        body = briefing_to_text(briefing)
        return f"帮你看了一下你现在的进度：\n{body}\n有需要的话，点页面下方的「拍照批改」就可以开始作答啦。"

    # 2) 某知识点的错题（消息里出现知识点名且带"错"字）
    if "错" in msg:
        for kp in _known_knowledge_points(db, student):
            if kp and kp in msg:
                items = knowledge_point_errors(db, student, kp, visible_only=True)
                return kp_errors_to_text(kp, items) + "\n把这些题的出错步再看一遍，然后去订正区试着改对它们吧。"

    # 3) 学习情况 / 最弱知识点
    if any(k in msg for k in _WEAK_KEYWORDS):
        report = student_report(db, student, visible_only=True)
        if not report or all(not s["knowledge_points"] for s in report):
            return "你目前还没有错题记录，各知识点都保持得不错。继续按节奏作答，报告会随着你的提交慢慢丰富起来。"
        # 找错误率最高的知识点作为"最需要加固"
        worst = None
        for subj in report:
            for kp in subj["knowledge_points"]:
                if worst is None or kp["error_rate"] > worst["error_rate"]:
                    worst = kp
        head = ""
        if worst:
            head = (
                f"你目前最需要加固的是「{worst['name']}」：提交 {worst['attempts']} 次、"
                f"出错 {worst['error_count']} 次（错误率 {round(worst['error_rate'] * 100)}%）。\n"
            )
        return head + "完整的学习情况是这样的：\n" + report_to_text(report)

    # 4) 打招呼
    if any(k in msg.lower() for k in _GREETING_KEYWORDS):
        briefing = student_briefing(db, student, visible_only=True)
        pending_n = len(briefing.get("pending_assignments", []))
        tail = (
            f"你还有 {pending_n} 份作业没完成，我们先把它们搞定？"
            if pending_n else
            "你的作业都完成了，今天想复习哪个知识点，或者聊聊数学问题都可以。"
        )
        return f"你好，{student.name}！我是你的数学学习助手。{tail}"

    # 5) 其他（数学闲聊/提问）：罐头讲解
    return _CANNED_EXPLANATION
