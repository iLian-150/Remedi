# LangGraph 图组装：agent 节点（带工具的 LLM）+ tools 节点（ToolNode）+ 条件边。
#
#   START → agent ──(tools_condition: 有 tool_calls)──→ tools → agent（循环）
#                 └──(无 tool_calls)──→ END
#
# LLM 走 Cloudflare Workers AI；配置缺失或调用失败时明确报错，不生成模拟回复。
import logging
from time import perf_counter
from typing import Annotated, List, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from ..services.stats import student_briefing
from .prompts import build_system_prompt
from .tools import build_tools

logger = logging.getLogger(__name__)


def _build_llm(*, streaming: bool = True):
    """构造统一使用 Cloudflare Workers AI 的对话模型。"""
    from langchain_openai import ChatOpenAI

    if settings.LLM_PROVIDER != "cloudflare":
        raise RuntimeError("提问模型必须配置为 Cloudflare Workers AI")
    if not settings.CLOUDFLARE_ACCOUNT_ID or not settings.CLOUDFLARE_API_TOKEN:
        raise RuntimeError("Cloudflare 模型凭证未配置")

    class TextSafeChatOpenAI(ChatOpenAI):
        """修正 Cloudflare 偶发返回的非文本 content，保留其余流式字段。"""

        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info
        ):
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
            if choices:
                delta = choices[0].get("delta")
                content = delta.get("content") if isinstance(delta, dict) else None
                if content is not None and not isinstance(content, (str, list)):
                    safe_chunk = dict(chunk)
                    safe_choices = [dict(choice) for choice in choices]
                    safe_delta = dict(delta)
                    safe_delta["content"] = ""
                    safe_choices[0]["delta"] = safe_delta
                    if chunk.get("choices"):
                        safe_chunk["choices"] = safe_choices
                    else:
                        nested = dict(chunk.get("chunk", {}))
                        nested["choices"] = safe_choices
                        safe_chunk["chunk"] = nested
                    chunk = safe_chunk
                    logger.debug(
                        "忽略 Cloudflare 流式响应中的非文本 content（%s）",
                        type(content).__name__,
                    )
            return super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )

    return TextSafeChatOpenAI(
        base_url=f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        api_key=settings.CLOUDFLARE_API_TOKEN,
        model=settings.CLOUDFLARE_MODEL,
        temperature=0.5,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=0,
        streaming=streaming,
    )


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


def _tools_used(messages: list) -> List[str]:
    """从图执行轨迹里抽本轮真实调用过的工具名（供建议气泡按意图映射，v0.6.0）。"""
    names: List[str] = []
    for msg in messages or []:
        for call in getattr(msg, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name and name not in names:
                names.append(name)
    return names


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


def _response_text(content) -> str:
    """把 OpenAI 兼容接口的文本内容归一化；忽略非文本响应块。"""
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
                       history: List[BaseMessage], user_text: str,
                       safe_tools_only: bool = False):
    """逐块输出 Agent 回复；迭代结束时返回回复全文和本轮调用的工具名。"""
    # 流式响应中的非文本 content 会在模型适配层被过滤；回复可以边生成边发送。
    llm = _build_llm(streaming=True)
    if safe_tools_only:
        # 照片讲解只依赖本轮已经识别和批改的内容。历史会话与学生近况不参与
        # 当前题目推理，省掉额外上下文，并避免重复上传造成的长历史拖慢模型。
        system = (
            "你是 Remedi 学习辅导老师。学生照片中的题目和作答已经识别，批改记录已经保存。"
            "只处理当前消息里的题目：先讲正确思路，再结合已识别的学生步骤说明关键对错；"
            "如果没有学生步骤，就只讲题。不要重复批改或调用任何写入工具。"
            "其他学科直接讲解。若系统给出错因待复核，不要把它说成最终结论。"
            "回答简洁、分步骤，避免冗长铺垫。"
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user_text)]
    else:
        system = build_system_prompt(student.name, _context_summary(db, student))
        messages = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
    related_result: dict = {"mistake": None}
    reply_parts: list[str] = []
    tool_names: dict[int, str] = {}
    reply = ""

    def direct_photo_explanation() -> str:
        """不依赖 LangChain 流式解析、工具或历史消息，直接讲解本次题目。"""
        from ..services.providers import get_provider

        content = get_provider()._chat(system, user_text, temperature=0.5)
        reply = _response_text(content).strip()
        if not reply:
            raise ValueError("模型直接讲解未返回文本内容")
        return reply

    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode, tools_condition

        class AgentState(TypedDict):
            messages: Annotated[list, add_messages]

        if safe_tools_only:
            # photo-review 已查好历史错题；直接生成讲解，省去模型选择只读工具的额外轮次。
            tools = []
            llm_with_tools = llm
        else:
            tools, related_result = build_tools(db, student)
            llm_with_tools = llm.bind_tools(tools)

        def call_model(state: AgentState):
            started_at = perf_counter()
            response = llm_with_tools.invoke(state["messages"])
            if safe_tools_only:
                logger.info(
                    "照片讲解模型轮次完成（耗时 %.2f 秒，工具调用数 %d）",
                    perf_counter() - started_at,
                    len(getattr(response, "tool_calls", None) or []),
                )
            return {"messages": [response]}

        builder = StateGraph(AgentState)
        builder.add_node("agent", call_model)
        builder.add_edge(START, "agent")
        if tools:
            builder.add_node("tools", ToolNode(tools))
            builder.add_conditional_edges("agent", tools_condition)
            builder.add_edge("tools", "agent")
        else:
            builder.add_edge("agent", END)
        graph = builder.compile()

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

    except Exception:
        if not safe_tools_only:
            logger.exception("Agent 流式调用失败")
            raise

        # 图片识别和批改结果已经包含在 user_text 中；历史错题查询是辅助能力，
        # 不能让工具绑定、工具执行或旧聊天上下文阻断学生获得本题讲解。
        logger.exception("照片讲解的 LangGraph 工具链失败，改用非流式直接讲解")
        try:
            fallback_started_at = perf_counter()
            fallback_reply = direct_photo_explanation()
            logger.info("照片讲解直接兜底完成（耗时 %.2f 秒）", perf_counter() - fallback_started_at)
            streamed_reply = "".join(reply_parts).strip()
            if streamed_reply and fallback_reply.startswith(streamed_reply):
                remainder = fallback_reply[len(streamed_reply):]
            elif streamed_reply:
                remainder = "\n\n补充讲解：\n" + fallback_reply
            else:
                remainder = fallback_reply
            if remainder:
                yield remainder
                reply_parts.append(remainder)
            reply = "".join(reply_parts).strip()
        except Exception:
            logger.exception("照片讲解的非流式直接生成兜底也失败")
            raise

    names = list(dict.fromkeys(name for name in tool_names.values() if name))
    return {
        "reply": reply,
        "tools_used": names,
        "related_mistake": related_result.get("mistake"),
    }
