"""Optional Milvus dense recall; SQLite remains the document source of truth.

Imports and connections are lazy so the default deployment needs no vector
service. Public errors deliberately omit remote responses and credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

import requests

from ..config import settings


_BATCH_SIZE = 10
_states_lock = RLock()


@dataclass
class _ClientState:
    client: Any
    timeout: float
    lock: RLock = field(default_factory=RLock)
    ready: dict[str, int] = field(default_factory=dict)


_states: dict[tuple[str, str, float], _ClientState] = {}


def configured() -> bool:
    """Whether dense recall was explicitly enabled by configuration."""
    return bool(settings.RAG_MILVUS_URI.strip())


def _timeout() -> float:
    value = float(settings.RAG_TIMEOUT_SECONDS)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("RAG 请求超时配置无效")
    return min(value, 30.0)


def _model() -> str:
    model = settings.RAG_EMBEDDING_MODEL.strip()
    if not model or len(model.encode("utf-8")) > 256:
        raise RuntimeError("RAG 向量模型配置无效")
    return model


def _embedding_key() -> str:
    token = settings.DASHSCOPE_API_KEY.strip()
    if not token:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，百炼向量服务暂不可用")
    return token


def _embedding_dimensions() -> int:
    dimension = settings.RAG_EMBEDDING_DIMENSIONS
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 2 <= dimension <= 32768:
        raise RuntimeError("RAG 向量维数配置无效")
    return dimension


def _embedding_endpoint() -> str:
    base_url = settings.DASHSCOPE_BASE_URL.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise RuntimeError("百炼向量服务地址配置无效")
    return base_url + "/embeddings"


def _validate_vectors(raw: Any, expected: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) != expected:
        raise RuntimeError("向量服务返回的数量不匹配")
    vectors: list[list[float]] = []
    dimension = 0
    for row in raw:
        if not isinstance(row, list) or not 2 <= len(row) <= 32768:
            raise RuntimeError("向量服务返回的维数无效")
        if dimension and len(row) != dimension:
            raise RuntimeError("向量服务返回的维数不一致")
        dimension = len(row)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in row):
            raise RuntimeError("向量服务返回了无效数值")
        vector = [float(value) for value in row]
        if not all(math.isfinite(value) for value in vector) or not any(vector):
            raise RuntimeError("向量服务返回了无效数值")
        vectors.append(vector)
    return vectors


def _ordered_embeddings(payload: Any, count: int, dimension: int) -> list[list[float]]:
    """Restore request order from OpenAI indices and reject ambiguous mappings."""
    if not isinstance(payload, dict) or "error" in payload:
        raise RuntimeError("向量服务返回格式无效")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise RuntimeError("向量服务返回的数量不匹配")
    by_index = {}
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("向量服务返回格式无效")
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count or index in by_index:
            raise RuntimeError("向量服务返回了重复、缺失或无效的文本索引")
        by_index[index] = item.get("embedding")
    if set(by_index) != set(range(count)):
        raise RuntimeError("向量服务返回了缺失的文本索引")
    vectors = _validate_vectors([by_index[index] for index in range(count)], count)
    if any(len(vector) != dimension for vector in vectors):
        raise RuntimeError("向量服务返回的维数与请求不匹配")
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed at most ten texts per Bailian request, without a local vector cache."""
    if not texts:
        return []
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("待向量化文本不能为空")
    token = _embedding_key()
    model = _model()
    dimension = _embedding_dimensions()
    endpoint = _embedding_endpoint()
    vectors: list[list[float]] = []
    timeout = _timeout()
    for offset in range(0, len(texts), _BATCH_SIZE):
        batch = texts[offset:offset + _BATCH_SIZE]
        try:
            with requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"model": model, "input": batch, "dimensions": dimension, "encoding_format": "float"},
                timeout=(min(3.0, timeout), timeout),
                allow_redirects=False,
            ) as response:
                response.raise_for_status()
                payload = response.json()
            batch_vectors = _ordered_embeddings(payload, len(batch), dimension)
            vectors.extend(batch_vectors)
        except Exception:
            raise RuntimeError("百炼向量服务调用失败或返回格式无效") from None
    return vectors


def _client_state() -> tuple[_ClientState, str]:
    uri = settings.RAG_MILVUS_URI.strip()
    parsed = urlsplit(uri)
    # A filename would silently enable Milvus Lite and store local vectors.
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("RAG_MILVUS_URI 必须是 Milvus 服务的 HTTP(S) 地址")
    collection = settings.RAG_MILVUS_COLLECTION.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", collection):
        raise RuntimeError("Milvus 集合名称无效")
    timeout = _timeout()
    key = (uri, settings.RAG_MILVUS_TOKEN.strip(), timeout)
    with _states_lock:
        state = _states.get(key)
        if state is None:
            try:
                from pymilvus import MilvusClient

                state = _ClientState(
                    MilvusClient(uri=uri, token=key[1], timeout=timeout), timeout,
                )
            except Exception:
                raise RuntimeError("Milvus 连接失败") from None
            _states[key] = state
    return state, collection


def _ensure_collection(state: _ClientState, collection: str, dimension: int) -> None:
    """Create/load once per client and collection, including concurrent callers."""
    with state.lock:
        if collection in state.ready:
            if state.ready[collection] != dimension:
                raise RuntimeError("Milvus 向量维数不匹配，请更换集合并重建索引")
            return
        from pymilvus import DataType, MilvusClient

        client = state.client
        if not client.has_collection(collection_name=collection, timeout=state.timeout):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
            schema.add_field(field_name="document_id", datatype=DataType.INT64)
            schema.add_field(field_name="subject", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="embedding_model", datatype=DataType.VARCHAR, max_length=256)
            schema.add_field(field_name="vectors", datatype=DataType.FLOAT_VECTOR, dim=dimension)
            indexes = client.prepare_index_params()
            indexes.add_index(field_name="vectors", index_type="AUTOINDEX", metric_type="COSINE")
            try:
                client.create_collection(
                    collection_name=collection, schema=schema, index_params=indexes,
                    consistency_level="Strong", timeout=state.timeout,
                )
            except Exception:
                # Another API worker can finish the same lazy initialization.
                if not client.has_collection(collection_name=collection, timeout=state.timeout):
                    raise
        description = client.describe_collection(collection_name=collection, timeout=state.timeout)
        fields = {item["name"]: item for item in description.get("fields", [])}
        required = {"id", "document_id", "subject", "embedding_model", "vectors"}
        if not required.issubset(fields) or int(fields["vectors"].get("params", {}).get("dim", 0)) != dimension:
            raise RuntimeError("Milvus 集合结构不匹配，请更换集合并重建索引")
        client.load_collection(collection_name=collection, timeout=state.timeout)
        state.ready[collection] = dimension


def _invalidate(state: _ClientState, collection: str) -> None:
    with state.lock:
        state.ready.pop(collection, None)


def _subject(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value):
        raise ValueError("学科代码无效")
    return value


def upsert_passages(subject: str, passages: list[dict]) -> None:
    """Idempotently synchronize passage IDs; vectors exist only in Milvus."""
    if not passages:
        return
    subject = _subject(subject)
    _embedding_key()
    model = _model()
    state, collection = _client_state()
    try:
        for offset in range(0, len(passages), _BATCH_SIZE):
            batch = passages[offset:offset + _BATCH_SIZE]
            vectors = embed_texts([
                f"{item.get('title') or ''}\n{item['content']}".strip() for item in batch
            ])
            _ensure_collection(state, collection, len(vectors[0]))
            rows = [
                {
                    "id": int(item["id"]), "document_id": int(item["document_id"]),
                    "subject": subject, "embedding_model": model, "vectors": vector,
                }
                for item, vector in zip(batch, vectors)
            ]
            state.client.upsert(collection_name=collection, data=rows, timeout=state.timeout)
    except Exception:
        _invalidate(state, collection)
        raise RuntimeError("Milvus 索引同步失败") from None


def delete_document(document_id: int) -> None:
    """Remove all model versions for one SQLite document, without creating a collection."""
    document_id = int(document_id)
    state, collection = _client_state()
    try:
        if not state.client.has_collection(collection_name=collection, timeout=state.timeout):
            return
        state.client.load_collection(collection_name=collection, timeout=state.timeout)
        state.client.delete(
            collection_name=collection, filter=f"document_id == {document_id}", timeout=state.timeout,
        )
    except Exception:
        _invalidate(state, collection)
        raise RuntimeError("Milvus 文档索引删除失败") from None


def search_passages(subject: str, query: str, limit: int = 24) -> list[tuple[int, float]]:
    """Recall only the requested subject and current embedding model on the server."""
    subject = _subject(subject)
    if not query.strip() or limit <= 0:
        return []
    vector = embed_texts([query])[0]
    state, collection = _client_state()
    try:
        _ensure_collection(state, collection, len(vector))
        results = state.client.search(
            collection_name=collection, data=[vector], anns_field="vectors",
            filter="subject == {subject} and embedding_model == {embedding_model}",
            filter_params={"subject": subject, "embedding_model": _model()},
            search_params={"metric_type": "COSINE", "params": {}},
            limit=min(int(limit), 256), output_fields=["id"],
            consistency_level="Strong", timeout=state.timeout,
        )
        hits = []
        for item in results[0] if results else []:
            score = float(item["distance"])
            if math.isfinite(score):
                hits.append((int(item["id"]), score))
        return hits
    except Exception:
        _invalidate(state, collection)
        raise RuntimeError("Milvus 检索失败") from None
