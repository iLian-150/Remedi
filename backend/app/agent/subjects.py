"""学科 Agent 注册表与按学科隔离的轻量 RAG 检索。"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from ..models import SubjectKnowledgeChunk


SUBJECT_AGENTS = {
    "chinese": ("语文", "以阅读理解、文言文、语言运用和写作规范为主；引用文本证据，区分原文信息与推断。"),
    "math": ("数学", "先梳理已知与目标，再逐步推理；检查符号、运算和适用条件，不跳过关键步骤。"),
    "english": ("英语", "关注语境、语法、词汇和自然表达；指出依据，并给出适合当前水平的改写。"),
    "politics": ("道法", "围绕材料、教材概念和设问组织答案；区分事实、观点和价值判断。"),
    "history": ("历史", "结合时序、背景、过程和影响分析；标明材料证据，避免把因果关系混为一谈。"),
    "physics": ("物理", "先辨认物理情境与研究对象，再列规律、条件、单位和计算步骤。"),
    "chemistry": ("化学", "关注物质、反应条件、现象、方程式和守恒关系，检查化学用语与配平。"),
    "geography": ("地理", "结合区域位置、自然与人文要素以及图表证据，按因果链解释现象。"),
    "biology": ("生物", "围绕结构与功能、生命过程和实验变量解释，使用准确的生物学概念。"),
}

SUBJECT_ALIASES = {
    "语文": "chinese", "数学": "math", "英语": "english", "道法": "politics",
    "道德与法治": "politics", "政治": "politics", "历史": "history", "物理": "physics",
    "化学": "chemistry", "地理": "geography", "生物": "biology",
}


def normalize_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return None
    value = subject.strip().lower()
    value = SUBJECT_ALIASES.get(value, value)
    return value if value in SUBJECT_AGENTS else None


def detect_subject(text: str, fallback: Optional[str] = None) -> Optional[str]:
    explicit = normalize_subject(fallback)
    if explicit:
        return explicit
    for label in sorted(SUBJECT_ALIASES, key=len, reverse=True):
        if label in text:
            return SUBJECT_ALIASES[label]
    return None


def _tokens(text: str) -> set[str]:
    normalized = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", normalized))
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    tokens.update("".join(chinese[i:i + 2]) for i in range(max(0, len(chinese) - 1)))
    tokens.update(chinese)
    return tokens


def retrieve_subject_knowledge(
    db: Session, subject: Optional[str], query: str, limit: int = 4,
) -> list[SubjectKnowledgeChunk]:
    """只查询选定学科的知识片段，避免九个 RAG 库之间串数据。"""
    normalized = normalize_subject(subject)
    if not normalized or not query.strip():
        return []
    query_tokens = _tokens(query)
    rows = db.query(SubjectKnowledgeChunk).filter(
        SubjectKnowledgeChunk.subject == normalized,
    ).order_by(SubjectKnowledgeChunk.created_at.desc()).limit(500).all()
    ranked = []
    for row in rows:
        content_tokens = _tokens(f"{row.title} {row.content}")
        overlap = len(query_tokens & content_tokens)
        if overlap:
            ranked.append((overlap, row))
    ranked.sort(key=lambda pair: (pair[0], pair[1].created_at, pair[1].id), reverse=True)
    return [row for _, row in ranked[:max(1, limit)]]


def build_subject_context(db: Session, subject: Optional[str], query: str) -> str:
    normalized = detect_subject(query, subject)
    if not normalized:
        return ""
    label, instruction = SUBJECT_AGENTS[normalized]
    chunks = retrieve_subject_knowledge(db, normalized, query)
    rag_text = "\n".join(
        f"- {item.title}：{item.content[:1200]}" for item in chunks
    ) or "本学科知识库没有检索到与本轮问题直接相关的资料；请依据可靠的学科知识回答，不要声称引用了库内资料。"
    return (
        f"当前路由到{label} Agent（{normalized}）。专属教学要求：{instruction}\n"
        f"{label} Agent 专属 RAG 检索结果：\n{rag_text}"
    )
