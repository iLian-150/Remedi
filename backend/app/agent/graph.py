# LangGraph 图组装：agent 节点（带工具的 LLM）+ tools 节点（ToolNode）+ 条件边。
#
#   START → agent ──(tools_condition: 有 tool_calls)──→ tools → agent（循环）
#                 └──(无 tool_calls)──→ END
#
# LLM 走 langchain_openai.ChatOpenAI，端点/模型/密钥全部从现有 settings 派生，
# 与 Provider 层共用同一套环境变量（cloudflare / deepseek 两条路走同一套图代码）。
# LLM_PROVIDER=mock、无凭证、或图调用任何异常 → 降级 mock_agent 规则回复，接口永不 500。
import logging
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from ..services.stats import student_briefing
from .mock_agent import mock_reply
from .prompts import build_system_prompt
from .tools import build_tools

logger = logging.getLogger(__name__)


def _build_llm():
    """按 settings 构造 ChatOpenAI；mock 或凭证缺失时返回 None（走规则兜底）。"""
    from langchain_openai import ChatOpenAI

    if settings.LLM_PROVIDER == "cloudflare":
        if not settings.CLOUDFLARE_ACCOUNT_ID or not settings.CLOUDFLARE_API_TOKEN:
            logger.info("Agent：cloudflare 凭证未配置，使用规则回复")
            return None
        return ChatOpenAI(
            base_url=f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/v1",
            api_key=settings.CLOUDFLARE_API_TOKEN,
            model=settings.CLOUDFLARE_MODEL,
            temperature=0.5,
            timeout=30,
            max_retries=1,
        )
    if settings.LLM_PROVIDER == "deepseek":
        if not settings.DEEPSEEK_API_KEY:
            logger.info("Agent：deepseek key 未配置，使用规则回复")
            return None
        return ChatOpenAI(
            base_url=settings.DEEPSEEK_BASE_URL,
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.DEEPSEEK_MODEL,
            temperature=0.5,
            timeout=30,
            max_retries=1,
        )
    return None


def _context_summary(db: Session, student: User) -> str:
    """学生近况摘要（注入系统提示词）：待办份数 + 需加固知识点，来自真实简报数据。"""
    try:
        b = student_briefing(db, student, visible_only=True)
    except Exception:
        return ""
    parts = []
    pending = b.get("pending_assignments", [])
    if pending:
        remaining = sum(p["remaining_count"] for p in pending)
        parts.append(f"还有 {len(pending)} 份作业未完成（共 {remaining} 题没做）")
    corr_n = b.get("pending_corrections_count", 0)
    if corr_n:
        parts.append(f"有 {corr_n} 处错题还没订正")
    weak = b.get("weak_points", [])
    if weak:
        parts.append(f"需要加固的知识点：{'、'.join(weak)}")
    if not parts:
        return "作业与订正都已完成，暂无需要加固的知识点，状态很好。"
    return "；".join(parts) + "。"


def _message_text(msg: BaseMessage) -> str:
    """规整模型返回：content 可能是 str 或内容块列表，统一抽成纯文本。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts).strip()
    return str(content).strip()


def _tools_used(messages: list) -> List[str]:
    """从图执行轨迹里抽本轮真实调用过的工具名（供建议气泡按意图映射，v0.6.0）。"""
    names: List[str] = []
    for msg in messages or []:
        for call in getattr(msg, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name and name not in names:
                names.append(name)
    return names


def agent_reply_full(db: Session, student: User,
                     history: List[BaseMessage], user_text: str) -> dict:
    """Agent 回复入口（带元信息）：优先跑 LangGraph 图；不可用/异常时降级规则回复。
    返回 {"reply": 回复文本, "tools_used": 本轮真实调用的工具名列表（降级时为空）}。"""
    try:
        llm = _build_llm()
    except Exception as e:
        logger.warning("Agent LLM 构造失败，降级为规则回复: %s", e)
        return {"reply": mock_reply(db, student, user_text), "tools_used": []}
    if llm is None:
        return {"reply": mock_reply(db, student, user_text), "tools_used": []}
    try:
        from langgraph.graph import START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode, tools_condition

        class AgentState(TypedDict):
            messages: Annotated[list, add_messages]

        tools = build_tools(db, student)
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

        system = build_system_prompt(student.name, _context_summary(db, student))
        messages = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
        result = graph.invoke({"messages": messages}, config={"recursion_limit": 15})
        reply = _message_text(result["messages"][-1])
        if not reply:
            raise ValueError("模型返回了空回复")
        return {"reply": reply, "tools_used": _tools_used(result["messages"])}
    except Exception as e:
        logger.warning("Agent 图调用失败，降级为规则回复: %s", e)
        return {"reply": mock_reply(db, student, user_text), "tools_used": []}


def _message_chunk_text(msg) -> str:
    """提取 LangChain 流式消息块中的文本，不裁掉块边界上的空格。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def agent_reply_stream(db: Session, student: User,
                       history: List[BaseMessage], user_text: str):
    """逐块输出 Agent 回复；迭代结束时返回回复全文和本轮调用的工具名。"""
    try:
        llm = _build_llm()
    except Exception as e:
        logger.warning("Agent LLM 构造失败，降级为规则回复: %s", e)
        reply = mock_reply(db, student, user_text)
        yield from reply
        return {"reply": reply, "tools_used": []}
    if llm is None:
        reply = mock_reply(db, student, user_text)
        yield from reply
        return {"reply": reply, "tools_used": []}

    try:
        from langgraph.graph import START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode, tools_condition

        class AgentState(TypedDict):
            messages: Annotated[list, add_messages]

        tools = build_tools(db, student)
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

        system = build_system_prompt(student.name, _context_summary(db, student))
        messages = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
        reply_parts: list[str] = []
        tool_names: dict[int, str] = {}

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
        names = list(dict.fromkeys(name for name in tool_names.values() if name))
        return {"reply": reply, "tools_used": names}
    except Exception as e:
        logger.warning("Agent 流式调用失败，降级为规则回复: %s", e)
        if 'reply_parts' in locals() and reply_parts:
            raise
        reply = mock_reply(db, student, user_text)
        yield from reply
        return {"reply": reply, "tools_used": []}


def agent_reply(db: Session, student: User,
                history: List[BaseMessage], user_text: str) -> str:
    """兼容旧签名的纯文本入口（v0.6.0 起内部走 agent_reply_full）。"""
    return agent_reply_full(db, student, history, user_text)["reply"]
