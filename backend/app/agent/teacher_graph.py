# 教师 Agent 图组装：与学生端 graph.py 同一套结构（agent 节点 + ToolNode + 条件边），
# LLM 构造与文本规整直接复用学生端实现；调用失败时明确报错，不生成模拟回复。
import logging
from typing import List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..models import User
from ..services.stats import knowledge_point_ranking
from ..services.teacher_stats import class_overview, uncorrected_overview
from .graph import _build_llm, _message_chunk_text
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


def teacher_agent_reply_stream(db: Session, teacher: User,
                               history: List[BaseMessage], user_text: str):
    """逐块输出教师 Agent 回复；迭代结束时返回全文和实际调用的工具名。"""
    llm = _build_llm()
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
    reply_parts: list[str] = []
    tool_names: dict[int, str] = {}
    try:
        for part in graph.stream(
            {"messages": messages},
            config={"recursion_limit": 15},
            stream_mode="messages",
            version="v2",
        ):
            if part.get("type") != "messages":
                continue
            message_chunk, metadata = part["data"]
            if metadata.get("langgraph_node") != "agent":
                continue
            text = _message_chunk_text(message_chunk)
            if text:
                reply_parts.append(text)
                yield text
            for call in getattr(message_chunk, "tool_call_chunks", None) or []:
                name = call.get("name")
                if name:
                    index = call.get("index", len(tool_names))
                    tool_names[index] = tool_names.get(index, "") + name

        reply = "".join(reply_parts).strip()
        if not reply:
            raise ValueError("模型返回了空回复")
        return {"reply": reply, "tools_used": list(dict.fromkeys(n for n in tool_names.values() if n))}
    except Exception:
        logger.exception("教师 Agent 流式调用失败")
        raise
