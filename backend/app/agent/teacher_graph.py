# 教师 Agent 图组装：与学生端 graph.py 同一套结构（agent 节点 + ToolNode + 条件边），
# LLM 构造与文本规整直接复用学生端实现，保证两条路（cloudflare / deepseek）配置一致。
# LLM_PROVIDER=mock、无凭证、或图调用任何异常 → 降级 teacher_mock 规则回复，接口永不 500。
import logging
from typing import List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..models import User
from ..services.stats import knowledge_point_ranking
from ..services.teacher_stats import class_overview, uncorrected_overview
from .graph import _build_llm, _message_text
from .teacher_mock import teacher_mock_reply
from .teacher_prompts import build_teacher_system_prompt
from .teacher_tools import build_teacher_tools

logger = logging.getLogger(__name__)


def _teacher_context_summary(db: Session) -> str:
    """班级近况摘要（注入系统提示词）：规模 + 最严重知识点 + 订正积压人数。"""
    try:
        ov = class_overview(db)
        parts = [f"共 {ov['student_count']} 名学生、{ov['assignment_count']} 份作业"]
        ranking = knowledge_point_ranking(db)
        if ranking:
            top = ranking[0]
            parts.append(
                f"错误率最高的知识点是「{top['knowledge_point']}」（{round(top['error_rate'] * 100)}%）"
            )
        pending = uncorrected_overview(db)
        if pending:
            parts.append(f"有 {len(pending)} 名学生的订正还没完成")
        return "；".join(parts) + "。"
    except Exception:
        return ""


def teacher_agent_reply_full(db: Session, teacher: User,
                             history: List[BaseMessage], user_text: str) -> dict:
    """教师 Agent 回复入口（带元信息）：优先跑 LangGraph 图；不可用/异常时降级规则回复。
    返回 {"reply": 回复文本, "tools_used": 本轮真实调用的工具名列表（降级时为空）}。"""
    try:
        llm = _build_llm()
    except Exception as e:
        logger.warning("教师 Agent LLM 构造失败，降级为规则回复: %s", e)
        return {"reply": teacher_mock_reply(db, teacher, user_text), "tools_used": []}
    if llm is None:
        return {"reply": teacher_mock_reply(db, teacher, user_text), "tools_used": []}
    try:
        from typing import Annotated, TypedDict

        from langgraph.graph import START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode, tools_condition

        class AgentState(TypedDict):
            messages: Annotated[list, add_messages]

        tools = build_teacher_tools(db, teacher)
        llm_with_tools = llm.bind_tools(tools)

        def call_model(state: AgentState):
            return {"messages": [llm_with_tools.invoke(state["messages"])]}

        builder = StateGraph(AgentState)
        builder.add_node("agent", call_model)
        builder.add_node("tools", ToolNode(tools))
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", tools_condition)
        builder.add_edge("tools", "agent")
        graph = builder.compile()

        system = build_teacher_system_prompt(teacher.name, _teacher_context_summary(db))
        messages = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
        result = graph.invoke({"messages": messages}, config={"recursion_limit": 15})
        reply = _message_text(result["messages"][-1])
        if not reply:
            raise ValueError("模型返回了空回复")
        from .graph import _tools_used

        return {"reply": reply, "tools_used": _tools_used(result["messages"])}
    except Exception as e:
        logger.warning("教师 Agent 图调用失败，降级为规则回复: %s", e)
        return {"reply": teacher_mock_reply(db, teacher, user_text), "tools_used": []}


def teacher_agent_reply(db: Session, teacher: User,
                        history: List[BaseMessage], user_text: str) -> str:
    """兼容旧签名的纯文本入口（v0.6.0 起内部走 teacher_agent_reply_full）。"""
    return teacher_agent_reply_full(db, teacher, history, user_text)["reply"]
