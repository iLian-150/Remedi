# 学生文字消息先经模型意图路由，再由 LangGraph 执行 agent 节点 + tools 节点。
#
#   意图路由 → 闲聊 / 错题总结 / 批改 / 学科答疑 / 学习数据
#   START → agent ──(tools_condition: 有 tool_calls)──→ tools → agent（循环）
#                 └──(无 tool_calls)──→ END
#
# LLM 走阿里云百炼；配置缺失或调用失败时明确报错，不生成模拟回复。
import logging
from time import perf_counter
from typing import Annotated, List, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from ..services.stats import student_briefing
from .prompts import build_system_prompt
from .subjects import (
    SUBJECT_AGENTS, build_subject_context, detect_subject, mentions_subject, normalize_subject,
)
from ..services.learning_memory import student_memory_to_text
from ..services.bailian_options import bailian_request_options, is_kimi_k3
from .tools import build_tools, student_notebook_to_text
from .rag_context import subject_retrieval_query as _subject_retrieval_query

logger = logging.getLogger(__name__)

_STUDENT_INTENTS = {
    "smalltalk": "闲聊或问候",
    "mistake_summary": "错题总结或个人薄弱点分析",
    "grading": "检查或批改学生作答",
    "tutoring": "学科学习答疑",
    "learning_data": "作业、订正进度或学习报告查询",
}
@tool("route_student_request")
def _route_student_request(
    intent: Literal["smalltalk", "mistake_summary", "grading", "tutoring", "learning_data"],
    subject: Literal[
        "chinese", "math", "english", "politics", "history", "physics",
        "chemistry", "geography", "biology", "unknown",
    ] = "unknown",
) -> str:
    """只记录学生本轮主要意图和学科，不回答问题、不读取或修改任何数据。"""
    return "路由已记录。"


def _resolve_student_subject(
    user_text: str,
    proposed_subject: str | None = None,
    fallback_subject: str | None = None,
) -> str | None:
    """Prefer one subject explicitly named now; preserve selected-subject context otherwise."""
    explicit_subject = detect_subject(user_text)
    if explicit_subject is not None:
        return explicit_subject
    if mentions_subject(user_text):
        # A current multi-subject question is ambiguous unless the UI supplied
        # an intentional active-subject context.
        return normalize_subject(fallback_subject)
    proposed = normalize_subject(proposed_subject) if isinstance(proposed_subject, str) else None
    return proposed or normalize_subject(fallback_subject)


def _fallback_student_route(user_text: str, fallback_subject: str | None = None) -> tuple[str, str | None]:
    """路由模型不可用时的保守兜底；只识别高置信度意图。"""
    text = (user_text or "").strip().lower()
    if any(word in text for word in (
        "批改", "检查一下", "对不对", "帮我看", "我写的是", "我的答案",
        "答案：", "答案:", "作答：", "作答:", "作文：", "作文:", "默写：", "默写:",
        "answer:", "my answer", "my work", "我的作答", "我的步骤", "我写了",
        "我做的是", "我算出来", "我认为是", "我认为答案", "解题过程",
    )):
        intent = "grading"
    elif any(phrase in text for phrase in (
        "加入错题本", "放进错题本", "放入错题本", "收录到错题本",
        "收藏到错题本", "保存到错题本", "记到错题本", "记入错题本",
        "加入我的错题本", "收藏这道题", "收录这道题",
    )):
        # 当前题目收录需要开放写入工具；不能落入只读的历史错题查询分支。
        intent = "tutoring"
    elif any(word in text for word in ("错题", "错因", "以前做错", "我哪里错", "薄弱点", "最弱")):
        intent = "mistake_summary"
    elif any(word in text for word in (
        "作业进度", "作业列表", "作业做完", "作业完成", "还有作业",
        "未完成", "没做", "还没做", "订正", "学习报告", "学习进度",
        "完成了多少", "还剩几",
    )):
        intent = "learning_data"
    elif len(text) <= 24 and any(word in text for word in ("你好", "您好", "在吗", "早上好", "晚上好", "你是谁", "谢谢", "hi", "hello")):
        intent = "smalltalk"
    else:
        intent = "tutoring"
    return intent, _resolve_student_subject(
        user_text, fallback_subject=fallback_subject,
    )


def _classify_student_request(
    history: List[BaseMessage], user_text: str, fallback_subject: str | None = None,
) -> tuple[str, str | None]:
    """用模型对统一文字入口做一次结构化分流；失败时回退到保守规则。"""
    fallback = _fallback_student_route(user_text, fallback_subject)
    system = SystemMessage(content=(
        "你是 Remedi 学习助手的意图路由器，只做分类，不回答学生。"
        "根据最后一条学生消息和必要的对话上下文，选择一个主要 intent 并调用 route_student_request。"
        "smalltalk=问候、闲聊、询问助手身份；mistake_summary=查询或总结本人错题、错因、薄弱点；"
        "grading=学生提交了本人作答并希望检查、批改或评分；tutoring=学科问题、只发题目求讲解；"
        "learning_data=作业/订正进度、学习报告等个人数据查询。"
        "只发题目而没有本人作答时选 tutoring。明确给出本人作答（数学过程、作文、默写或其他作答），即使没说检查，也选 grading。"
        "明确要求把当前题目加入、保存、收藏或收录到错题本时，不要归为 mistake_summary；选 tutoring（没有本人作答时照常讲题，主 Agent 会一并使用收录工具）。"
        "subject 只在本轮确实涉及某一学科题目或作答时填写九个代码之一；纯闲聊、个人数据查询、"
        "多学科比较或无法确定时填写 unknown。必须调用 route_student_request，不要输出自然语言。"
    ))
    try:
        router = _build_llm(
            streaming=False,
            temperature=0,
            timeout_seconds=min(settings.LLM_TIMEOUT_SECONDS, 15),
        ).bind_tools([_route_student_request])
        response = router.invoke([
            system,
            *history[-6:],
            HumanMessage(content=user_text),
        ])
        calls = getattr(response, "tool_calls", None) or []
        args = next((call.get("args", {}) for call in calls
                     if call.get("name") == "route_student_request"), {})
        intent = args.get("intent")
        if intent not in _STUDENT_INTENTS:
            logger.info("学生 Agent 路由未返回结构化结果，采用保守路由")
            fallback_intent, fallback_detected_subject = fallback
            return (
                fallback_intent,
                fallback_detected_subject
                if fallback_intent in {"grading", "tutoring"} else None,
            )
        raw_subject = args.get("subject")
        subject = _resolve_student_subject(
            user_text, raw_subject, fallback_subject,
        )
        if intent == "mistake_summary" and fallback[0] in {"grading", "tutoring"}:
            # 对明确批改/收录当前题目的请求，纠正模型误分到只读错题查询的情况。
            intent = fallback[0]
            subject = _resolve_student_subject(
                user_text, raw_subject, fallback_subject,
            )
        if intent not in {"grading", "tutoring"}:
            subject = None
        return intent, subject
    except Exception:
        logger.warning("学生 Agent 意图识别失败，使用保守路由", exc_info=True)
        intent, subject = fallback
        return intent, subject if intent in {"grading", "tutoring"} else None


def _build_llm(
    *, streaming: bool = True, temperature: float = 0.5,
    timeout_seconds: int | None = None,
):
    """构造使用百炼 OpenAI 兼容 Chat Completions 的对话与工具模型。"""
    if settings.LLM_PROVIDER.strip().lower() not in {"bailian", "dashscope", "aliyun"}:
        raise RuntimeError("提问模型必须配置为阿里云百炼（bailian）")
    if not settings.DASHSCOPE_API_KEY.strip():
        raise RuntimeError("未配置 DASHSCOPE_API_KEY（阿里云百炼）")
    if not settings.DASHSCOPE_BASE_URL.strip() or not settings.DASHSCOPE_MODEL.strip():
        raise RuntimeError("阿里云百炼接口地址或模型名称未配置")
    from langchain_openai import ChatOpenAI

    class TextSafeChatOpenAI(ChatOpenAI):
        """仅输出答复文本，并在当前工具调用上下文中回传 K3 的推理字段。"""

        def _create_chat_result(self, response, generation_info=None):
            result = super()._create_chat_result(response, generation_info)
            if is_kimi_k3(self.model_name):
                raw = response if isinstance(response, dict) else response.model_dump()
                for generation, choice in zip(result.generations, raw.get("choices") or []):
                    reasoning = (choice.get("message") or {}).get("reasoning_content")
                    if isinstance(reasoning, str):
                        generation.message.additional_kwargs["reasoning_content"] = reasoning
            return result

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            messages = self._convert_input(input_).to_messages()
            payload = super()._get_request_payload(messages, stop=stop, **kwargs)
            if is_kimi_k3(self.model_name):
                for serialized, message in zip(payload.get("messages") or [], messages):
                    if isinstance(message, AIMessage):
                        reasoning = message.additional_kwargs.get("reasoning_content")
                        if isinstance(reasoning, str):
                            serialized["reasoning_content"] = reasoning
            return payload

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
                        "忽略百炼流式响应中的非文本 content（%s）",
                        type(content).__name__,
                    )
            generation = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if generation is not None and is_kimi_k3(self.model_name) and choices:
                delta = choices[0].get("delta")
                reasoning = delta.get("reasoning_content") if isinstance(delta, dict) else None
                if isinstance(reasoning, str):
                    generation.message.additional_kwargs["reasoning_content"] = reasoning
            return generation

    options = bailian_request_options(settings.DASHSCOPE_MODEL, temperature)
    return TextSafeChatOpenAI(
        base_url=settings.DASHSCOPE_BASE_URL,
        api_key=settings.DASHSCOPE_API_KEY,
        model=settings.DASHSCOPE_MODEL,
        temperature=options.pop("temperature", None),
        timeout=timeout_seconds or settings.LLM_TIMEOUT_SECONDS,
        max_retries=0,
        streaming=streaming,
        use_responses_api=False,
        extra_body=options,
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


def agent_reply_stream(db: Session, student: User,
                       history: List[BaseMessage], user_text: str,
                       safe_tools_only: bool = False,
                       subject: str | None = None):
    """逐块输出 Agent 回复；迭代结束时返回回复全文和本轮调用的工具名。"""
    # 流式响应中的非文本 content 会在模型适配层被过滤；回复可以边生成边发送。
    llm = _build_llm(streaming=True)
    if safe_tools_only:
        intent = "tutoring"
        subject = detect_subject(user_text, subject)
    else:
        intent, subject = _classify_student_request(history, user_text, subject)
        logger.info(
            "学生 Agent 意图路由完成（intent=%s, subject=%s, student_id=%s）",
            intent, subject or "unknown", student.id,
        )
    rag_query = (
        _subject_retrieval_query(history, user_text, subject)
        if not safe_tools_only else user_text
    )
    subject_context = (
        build_subject_context(db, subject, rag_query)
        if intent in {"grading", "tutoring"} and subject else ""
    )
    if safe_tools_only:
        # 不传整段会话历史，但提供该学生最近错题作为个性化讲解依据。
        try:
            mistake_context = student_notebook_to_text(db, student, limit=5)
            memory_context = student_memory_to_text(db, student.id, limit=5)
        except Exception:
            logger.exception("读取照片答疑的学生错题本失败，student_id=%s", student.id)
            mistake_context = "当前无法读取历史错题。"
            memory_context = "当前无法读取长期学习记忆。"
        system = (
            "你是 Remedi 学习辅导老师。学生照片中的题目和作答已经识别，批改记录已经保存。"
            "只处理当前消息里的题目：先讲正确思路，再结合已识别的学生步骤说明关键对错；"
            "如果没有学生步骤，就只讲题。不要重复批改或调用任何写入工具。"
            f"{subject_context}\n"
            "可以参考下面该学生本人错题本中的同类错题进行个性化讲解；不要把自主收录说成答错。"
            "若条目标注待教师审核，必须说明那是暂定判断，不要说成最终结论。"
            f"\n学生错题本摘要：{mistake_context}\n"
            f"学生学习记忆：{memory_context}\n"
            "回答简洁、分步骤，避免冗长铺垫。"
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user_text)]
    else:
        route_context = f"主要意图：{_STUDENT_INTENTS[intent]}。"
        if subject:
            route_context += f"自动识别学科：{SUBJECT_AGENTS[subject][0]}。"
        else:
            route_context += "本轮无需指定单一学科。"
        context_summary = (
            "本轮是闲聊，不读取或引用学生学习数据。"
            if intent == "smalltalk" else _context_summary(db, student)
        )
        system = build_system_prompt(
            student.name, context_summary, subject_context, route_context,
        )
        if intent != "smalltalk":
            try:
                system += "\n\n学生学科记忆：\n" + student_memory_to_text(db, student.id, limit=5)
            except Exception:
                logger.exception("读取学习记忆失败，student_id=%s", student.id)
        messages = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
    related_result: dict = {"mistake": None}
    reply_parts: list[str] = []
    tool_names: list[str] = []
    reply = ""

    def direct_photo_explanation():
        """LangGraph 失败时绕过工具链，仍从模型 SSE 流逐块讲解本次题目。"""
        from ..services.providers import get_provider

        yield from get_provider().stream_chat_answer(system, user_text, temperature=0.5)

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
            tools, related_result = build_tools(
                db, student, routed_subject=subject, subject_context=subject_context,
            )
            if intent == "smalltalk":
                # 闲聊分支不开放任何学生数据工具，避免无关问题触发个人信息查询。
                tools = []
            elif intent == "mistake_summary":
                # 错题总结只开放读取工具，不能在查询历史时意外写入新诊断。
                read_only = {
                    "get_my_report", "get_my_mistake_notebook",
                    "get_my_learning_memory", "get_knowledge_point_errors",
                }
                tools = [item for item in tools if item.name in read_only]
            elif intent == "learning_data":
                # 进度/报告查询只开放读取工具。
                read_only = {
                    "get_my_briefing", "get_my_report", "get_my_mistake_notebook",
                    "get_my_learning_memory", "get_knowledge_point_errors",
                }
                tools = [item for item in tools if item.name in read_only]
            llm_with_tools = llm.bind_tools(tools) if tools else llm

        def call_model(state: AgentState):
            started_at = perf_counter()
            response = llm_with_tools.invoke(state["messages"])
            for name in _tools_used([response]):
                if name not in tool_names:
                    tool_names.append(name)
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
            # 只限制工具节点；顶层流式调度还需要独立线程等待消息。
            builder.add_node("tools", ToolNode(tools).with_config(max_concurrency=1))
            builder.add_conditional_edges("agent", tools_condition)
            builder.add_edge("tools", "agent")
        else:
            builder.add_edge("agent", END)
        graph = builder.compile()

        stream_started_at = perf_counter()
        first_text_logged = False
        graph_stream = graph.stream(
            {"messages": messages},
            config={"recursion_limit": 15},
            stream_mode="messages",
            version="v2",
        )
        try:
            for part in graph_stream:
                if part.get("type") != "messages":
                    continue
                message_chunk, metadata = part["data"]
                if metadata.get("langgraph_node") != "agent":
                    continue
                text = _message_chunk_text(message_chunk)
                if text:
                    if safe_tools_only and not first_text_logged:
                        first_text_logged = True
                        logger.info(
                            "照片讲解首字延迟（%.2f 秒）",
                            perf_counter() - stream_started_at,
                        )
                    reply_parts.append(text)
                    yield text
        finally:
            close = getattr(graph_stream, "close", None)
            if close is not None:
                close()

        reply = "".join(reply_parts).strip()
        if not reply:
            raise ValueError("模型返回了空回复")
        if safe_tools_only:
            logger.info(
                "照片讲解流完成（总耗时 %.2f 秒，输出字符数 %d）",
                perf_counter() - stream_started_at, len(reply),
            )

    except Exception:
        if not safe_tools_only:
            logger.exception("Agent 流式调用失败")
            raise

        # 图片识别和批改结果已经包含在 user_text 中；历史错题查询是辅助能力，
        # 不能让工具绑定、工具执行或旧聊天上下文阻断学生获得本题讲解。
        logger.exception("照片讲解的 LangGraph 工具链失败，改用直接流式讲解")
        try:
            fallback_started_at = perf_counter()
            streamed_reply = "".join(reply_parts)
            matched = 0
            diverged = False
            fallback_had_text = False
            fallback_stream = direct_photo_explanation()
            try:
                for chunk in fallback_stream:
                    if not chunk:
                        continue
                    fallback_had_text = True
                    if not streamed_reply:
                        yield chunk
                        reply_parts.append(chunk)
                        continue
                    for character in chunk:
                        if not diverged and matched < len(streamed_reply) and character == streamed_reply[matched]:
                            matched += 1
                            continue
                        if not diverged:
                            diverged = True
                            if matched < len(streamed_reply):
                                supplement = "\n\n补充讲解：\n"
                                yield supplement
                                reply_parts.append(supplement)
                        yield character
                        reply_parts.append(character)
            finally:
                close = getattr(fallback_stream, "close", None)
                if close is not None:
                    close()
            if not fallback_had_text:
                raise ValueError("模型直接讲解未返回文本内容")
            logger.info("照片讲解直接流式兜底完成（耗时 %.2f 秒）", perf_counter() - fallback_started_at)
            reply = "".join(reply_parts).strip()
            if not reply:
                raise ValueError("模型直接讲解未返回文本内容")
        except Exception:
            logger.exception("照片讲解的直接流式兜底也失败")
            raise

    return {
        "reply": reply,
        "tools_used": list(tool_names),
        "related_mistake": related_result.get("mistake"),
    }
