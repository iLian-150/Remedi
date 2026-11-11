"""Bounded OpenAI-compatible text reranking, without remote response in errors."""
from __future__ import annotations

import math
from urllib.parse import urlsplit, urlunsplit

import requests

from ..config import settings


MAX_CANDIDATES = 24
MAX_DOCUMENT_CHARS = 1000
MAX_QUERY_CHARS = 2000
def configured() -> bool:
    """An unset key or disabled model keeps local reranking silent and offline."""
    token = (settings.RAG_API_KEY.strip() or settings.LLM_API_KEY.strip()
             or settings.DASHSCOPE_API_KEY.strip())
    return bool(token and settings.RAG_RERANK_MODEL.strip())


def _endpoint() -> str:
    base_url = (settings.RAG_BASE_URL.strip().rstrip("/")
                or settings.LLM_BASE_URL.strip().rstrip("/")
                or settings.DASHSCOPE_BASE_URL.strip().rstrip("/"))
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise ValueError("invalid endpoint configuration")
    # Reading port also validates a malformed/non-numeric port before sending.
    parsed.port
    path = parsed.path.rstrip("/") + "/rerank"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _scores(payload: object, count: int) -> list[float]:
    if not isinstance(payload, dict) or payload.get("code") or "error" in payload:
        raise ValueError("invalid rerank response")
    results = payload.get("results")
    # Keep accepting the legacy DashScope response while new deployments use
    # the AI Ping-compatible /rerank response shape.
    if results is None:
        output = payload.get("output")
        results = output.get("results") if isinstance(output, dict) else None
    if not isinstance(results, list) or len(results) != count:
        raise ValueError("incomplete rerank response")
    by_index: dict[int, float] = {}
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("invalid rerank result")
        index = item.get("index")
        score = item.get("relevance_score")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count or index in by_index:
            raise ValueError("invalid rerank index")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError("invalid rerank score")
        value = float(score)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("invalid rerank score")
        by_index[index] = value
    if set(by_index) != set(range(count)):
        raise ValueError("missing rerank index")
    return [by_index[index] for index in range(count)]


def rerank_documents(query: str, documents: list[str]) -> list[float]:
    """Return one score per input document, retaining its original position.

    Only compact child passages are sent. Callers retain local ordering when
    this function raises; no partially validated results escape the adapter.
    """
    if not documents:
        return []
    if not isinstance(query, str) or not query.strip():
        raise ValueError("重排问题不能为空")
    if len(documents) > MAX_CANDIDATES or any(not isinstance(text, str) or not text.strip() for text in documents):
        raise ValueError("重排候选须为 1 至 24 条非空文本")
    token = (settings.RAG_API_KEY.strip() or settings.LLM_API_KEY.strip()
             or settings.DASHSCOPE_API_KEY.strip())
    if not token:
        raise RuntimeError("未配置 RAG_API_KEY 或 LLM_API_KEY，重排服务暂不可用")
    try:
        model = settings.RAG_RERANK_MODEL.strip()
        timeout = float(settings.RAG_RERANK_TIMEOUT_SECONDS)
        if not model or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid rerank configuration")
        timeout = min(timeout, 30.0)
        with requests.post(
            _endpoint(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "model": model,
                "query": query.strip()[:MAX_QUERY_CHARS],
                "documents": [text.strip()[:MAX_DOCUMENT_CHARS] for text in documents],
                "top_n": len(documents),
                "return_documents": False,
            },
            timeout=(min(3.0, timeout), timeout),
            allow_redirects=False,
        ) as response:
            response.raise_for_status()
            if not 200 <= response.status_code < 300:
                raise ValueError("unexpected rerank status")
            payload = response.json()
        return _scores(payload, len(documents))
    except Exception:
        raise RuntimeError("重排服务调用失败或返回格式无效") from None
