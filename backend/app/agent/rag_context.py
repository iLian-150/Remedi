"""Conversation-aware query expansion shared by student and teacher RAG."""
from langchain_core.messages import BaseMessage, HumanMessage

from .subjects import detect_subject, mentions_subject


_FOLLOW_UP_MARKERS = (
    "这个", "这些", "那一步", "这一步", "那种", "这种", "它", "上面", "刚才",
    "继续", "还有吗", "还有呢", "还有别的", "还有其他", "换一种", "再讲", "再说",
    "再解释", "展开说", "详细讲", "然后呢", "为什么呢", "怎么呢",
)
_ACKNOWLEDGEMENTS = {"谢谢", "好的", "明白", "嗯", "是的", "行", "收到", "好", "ok", "thanks"}


def _is_rag_follow_up(text: str) -> bool:
    value = (text or "").strip()
    if len(value) > 48:
        return False
    normalized = value.lower().rstrip(" ?？.!。！")
    return normalized in {"为什么", "怎么做", "怎么回事", "还有吗"} or any(
        marker in value for marker in _FOLLOW_UP_MARKERS
    )


def subject_retrieval_context(
    history: list[BaseMessage], user_text: str, subject: str | None,
) -> tuple[str, str | None]:
    """Expand a short follow-up and inherit an explicit recent subject when safe."""
    current = (user_text or "").strip()
    if not _is_rag_follow_up(current):
        return current, subject

    for message in reversed(history[-12:]):
        if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
            continue
        previous = message.content.strip()
        if not previous or previous.lower() in _ACKNOWLEDGEMENTS:
            continue
        if _is_rag_follow_up(previous):
            continue
        previous_subject = detect_subject(previous)
        if subject is not None and previous_subject is not None and previous_subject != subject:
            continue
        if previous_subject is None and mentions_subject(previous):
            continue
        return (
            f"{previous[:1600]}\n{current}"[:2000],
            subject or previous_subject,
        )
    return current, subject


def subject_retrieval_query(
    history: list[BaseMessage], user_text: str, subject: str | None,
) -> str:
    """Make a short anaphoric follow-up searchable from recent same-subject context."""
    return subject_retrieval_context(history, user_text, subject)[0]
