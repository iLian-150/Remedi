# 对话后「建议气泡」的规则映射（v0.6.0 新增，双端共用思路）。
#
# 每轮助手回复后，前端在最新回复下方弹出最多 3 条可点发送的后续问题。
# 建议不额外调 LLM：按「本轮意图」查表——意图优先取本轮真实调用过的工具
# （LLM 路径），取不到工具时按用户消息关键词判定。
# 每条建议都必须是对应 Agent 用现有工具能答上来的问题，避免点了答不出。

# ---------------- 学生端 ----------------

_STUDENT_TODO_KEYWORDS = ("没做", "未完成", "待办", "没交", "还有哪些作业", "还有什么作业", "要做什么")
_STUDENT_WEAK_KEYWORDS = ("最弱", "薄弱", "最差", "需要加固", "掌握", "报告", "学得怎么样", "学习情况")
_STUDENT_GREETING_KEYWORDS = ("你好", "您好", "hi", "hello", "在吗", "早上好", "晚上好")

_STUDENT_TOOL_INTENT = {
    "get_my_briefing": "todo",
    "get_knowledge_point_errors": "kp_errors",
    "get_my_report": "report",
}

_STUDENT_SUGGESTIONS = {
    "todo": ["我哪个知识点最需要加固", "看看我的学习报告", "给我讲讲移项为什么要变号"],
    "kp_errors": ["我还有哪些作业没做", "看看我的学习报告", "再给我讲讲这个知识点"],
    "report": ["我还有哪些作业没做", "给我讲讲这个知识点", "看看我的学习报告"],
    "math_qa": ["我还有哪些作业没做", "我哪个知识点最弱", "看看我的学习报告"],
    "greeting": ["我还有哪些作业没做", "我哪个知识点最需要加固", "看看我的学习报告"],
    "default": ["我还有哪些作业没做", "我哪个知识点最需要加固", "看看我的学习报告"],
}


def student_intent(message: str, tools_used: list | None = None) -> str:
    """判定学生本轮意图：先看真实用过的工具，再按关键词路由。"""
    for tool in tools_used or []:
        if tool in _STUDENT_TOOL_INTENT:
            return _STUDENT_TOOL_INTENT[tool]
    msg = (message or "").strip()
    if any(k in msg for k in _STUDENT_TODO_KEYWORDS):
        return "todo"
    if "错" in msg:
        return "kp_errors"
    if any(k in msg for k in _STUDENT_WEAK_KEYWORDS):
        return "report"
    if any(k in msg.lower() for k in _STUDENT_GREETING_KEYWORDS):
        return "greeting"
    if msg:
        return "math_qa"
    return "default"


def student_suggestions(message: str, tools_used: list | None = None) -> list:
    return list(_STUDENT_SUGGESTIONS[student_intent(message, tools_used)])


# ---------------- 教师端 ----------------

_TEACHER_REPAIR_KEYWORDS = ("修复率", "修复")
_TEACHER_RANKING_KEYWORDS = ("知识点", "错误率", "最严重", "最薄弱", "薄弱", "排行")
_TEACHER_CORRECTION_KEYWORDS = ("订正",)
_TEACHER_SUBMIT_KEYWORDS = ("没交", "未交", "还没交", "没做完", "提交情况", "交了", "提交了多少", "多少人交", "谁没")
_TEACHER_OVERVIEW_KEYWORDS = ("总览", "全班", "班级情况", "多少人", "多少学生", "整体")
_TEACHER_GREETING_KEYWORDS = ("你好", "您好", "hi", "hello", "在吗")

_TEACHER_TOOL_INTENT = {
    "get_assignment_status": "submit",
    "get_knowledge_point_ranking": "ranking",
    "get_class_repair_rate": "repair",
    "get_uncorrected_students": "uncorrected",
    "get_student_profile": "profile",
    "get_class_overview": "overview",
    "search_teaching_knowledge": "knowledge",
    "get_teaching_suggestions": "teaching_suggestions",
}

_TEACHER_SUGGESTIONS = {
    "submit": ["看看谁还没订正", "哪个知识点错误率最高", "班级知识修复率怎么样"],
    "ranking": ["今天谁还没交作业", "班级知识修复率怎么样", "谁的订正还没完成"],
    "repair": ["哪个知识点错误率最高", "谁的订正还没完成", "今天谁还没交作业"],
    "uncorrected": ["今天谁还没交作业", "哪个知识点错误率最高", "班级知识修复率怎么样"],
    "profile": ["哪个知识点错误率最高", "谁的订正还没完成", "班级知识修复率怎么样"],
    "overview": ["今天谁还没交作业", "哪个知识点错误率最高", "班级知识修复率怎么样"],
    "knowledge": [
        "根据刚才检索的资料，整理一份课堂讲解提纲",
        "基于这份资料设计一道课堂练习并附答案",
        "指出这份资料中学生容易混淆的概念",
    ],
    "teaching_suggestions": [
        "展开错误率最高知识点的分层讲解方案",
        "根据订正积压情况安排辅导顺序",
        "为最需要巩固的知识点设计一份练习",
    ],
    "greeting": ["今天谁还没交作业", "哪个知识点错误率最高", "班级知识修复率怎么样"],
    "default": ["今天谁还没交作业", "哪个知识点错误率最高", "班级知识修复率怎么样"],
}


def teacher_intent(message: str, tools_used: list | None = None) -> str:
    """判定教师本轮意图：先看真实用过的工具，再按关键词路由。"""
    for tool in tools_used or []:
        if tool in _TEACHER_TOOL_INTENT:
            return _TEACHER_TOOL_INTENT[tool]
    msg = (message or "").strip()
    if any(k in msg for k in _TEACHER_REPAIR_KEYWORDS):
        return "repair"
    if any(k in msg for k in _TEACHER_CORRECTION_KEYWORDS):
        return "uncorrected"
    if any(k in msg for k in _TEACHER_RANKING_KEYWORDS):
        return "ranking"
    if any(k in msg for k in _TEACHER_SUBMIT_KEYWORDS):
        return "submit"
    if any(k in msg.lower() for k in _TEACHER_GREETING_KEYWORDS):
        return "greeting"
    if any(k in msg for k in _TEACHER_OVERVIEW_KEYWORDS):
        return "overview"
    return "default"


def teacher_suggestions(message: str, tools_used: list | None = None) -> list:
    return list(_TEACHER_SUGGESTIONS[teacher_intent(message, tools_used)])
