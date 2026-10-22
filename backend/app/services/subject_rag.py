"""学科知识库检索：父子分块、BM25/Milvus 混合召回与可追溯上下文。

SQL 保存原文和片段，Milvus 仅作为可重建的向量索引。向量服务故障时，
不阻断资料保存或学科答疑；检索回退到同一学科的 BM25。
"""
import logging
import math
import re
import unicodedata
from collections import Counter, defaultdict

from sqlalchemy import event
from sqlalchemy.orm import Session

from ..models import SubjectKnowledgeChunk, SubjectKnowledgePassage
from . import bailian_rerank, rag_milvus
from .rag_quality import formula_tokens, spread_by_document

logger = logging.getLogger(__name__)

PARENT_SIZE = 1800
CHILD_SIZE = 520
CHILD_OVERLAP = 80
_RRF_K = 60
_STOP_TOKENS = {
    "什么", "怎么", "如何", "为什么", "为何", "这个", "那个", "一下", "帮我",
    "请问", "请你", "可以", "一下", "一个", "一些", "我们", "你们", "他们",
    "我的", "你的", "中的", "的是", "是否", "有关", "关于", "进行", "以及",
    "知识", "问题", "资料", "内容", "方法", "学习", "讲解", "解释", "分析",
    "the", "and", "for", "are", "what", "how", "please", "this", "that", "with",
}
_SINGLE_CJK_STOP_TOKENS = frozenset(
    "的一了着过是在有和与及或而但被把让从到对为以将于向跟给就都也还又再很太最非每各某这那此彼其它我你他她们谁哪什么不"
)
_VECTOR_WARNING = "向量检索尚未就绪，请检查向量模型和 Milvus 配置；当前使用 BM25，恢复后可重新建立向量索引。"
_RERANK_WARNING = "百炼重排暂不可用，当前使用本地排序。"
_WRITE_TRANSACTION = "_remedi_rag_write_transaction"
_SESSION_WRITE_TRANSACTION = "_remedi_session_write_transaction"


@event.listens_for(Session, "after_flush")
def _remember_knowledge_write(db: Session, _context) -> None:
    changed = [item for collection in (db.new, db.dirty, db.deleted) for item in collection]
    if changed:
        db.info[_SESSION_WRITE_TRANSACTION] = db.get_transaction()
    # AUTOINCREMENT 的已回滚 ID 仍可被复用。记录写事务，禁止将未提交 ID 发给 Milvus。
    if any(isinstance(item, (SubjectKnowledgeChunk, SubjectKnowledgePassage)) for item in changed):
        db.info[_WRITE_TRANSACTION] = db.get_transaction()


def _has_uncommitted_knowledge(db: Session) -> bool:
    transaction = db.info.get(_WRITE_TRANSACTION)
    return ((transaction is not None and transaction is db.get_transaction())
            or any(isinstance(item, (SubjectKnowledgeChunk, SubjectKnowledgePassage))
                   for collection in (db.new, db.dirty, db.deleted) for item in collection))


def _has_uncommitted_session_writes(db: Session) -> bool:
    transaction = db.info.get(_SESSION_WRITE_TRANSACTION)
    return ((transaction is not None and transaction is db.get_transaction())
            or bool(db.new or db.dirty or db.deleted))


def _tokenize(text: str, single_cjk_token: str | None = None) -> list[str]:
    """中文按连续词段生成二元词；仅针对有意义的单字查询开放单字匹配。"""
    formulas = formula_tokens(text or "")
    value = unicodedata.normalize("NFKC", text or "").lower()
    tokens = re.findall(r"[a-z][a-z0-9_]+|\d+(?:\.\d+)?", value)
    if single_cjk_token:
        tokens.extend([single_cjk_token] * value.count(single_cjk_token))
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return [token for token in tokens if token not in _STOP_TOKENS] + formulas


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """优先在自然段/句末切分，超长句仍有界切分，滑窗保留相邻条件。"""
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    chunks = []
    start = 0
    while start < len(value):
        end = min(start + size, len(value))
        if end < len(value):
            lower = start + size // 2
            candidates = [value.rfind(mark, lower, end) for mark in ("\n", "。", "！", "？", ";", "；", ". ")]
            boundary = max(candidates)
            if boundary >= lower:
                end = boundary + 1
        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(value):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _passage_data(document, pages=None) -> list[dict]:
    records = []
    parent_index = 0
    for page_number, text in pages if pages is not None else [(None, document.content)]:
        for parent in _split_text(text, PARENT_SIZE, 120):
            for child in _split_text(parent, CHILD_SIZE, CHILD_OVERLAP):
                records.append({
                    "document_id": document.id,
                    "parent_index": parent_index,
                    "chunk_index": len(records),
                    "content": child,
                    "parent_content": parent,
                    "page_number": page_number,
                })
            parent_index += 1
    return records


def _ensure_passages(db: Session, document, pages=None) -> list[SubjectKnowledgePassage]:
    # 重建向量时复用已有片段和页码；只有无片段的历史文本才重新切分。
    db.flush()
    passages = db.query(SubjectKnowledgePassage).filter_by(document_id=document.id).order_by(
        SubjectKnowledgePassage.chunk_index, SubjectKnowledgePassage.id,
    ).all()
    if passages:
        return passages
    passages = [SubjectKnowledgePassage(**record) for record in _passage_data(document, pages)]
    db.add_all(passages)
    db.flush()
    return passages


def _vector_records(document, passages) -> list[dict]:
    return [{"id": item.id, "document_id": document.id, "title": document.title, "content": item.content}
            for item in passages]


def _sync_vectors(subject: str, records: list[dict]) -> tuple[str, list[str]]:
    if not rag_milvus.configured():
        return "disabled", []
    try:
        if records:
            rag_milvus.upsert_passages(subject, records)
        return "ready", []
    except Exception as exc:
        logger.warning("学科向量索引同步失败（subject=%s, error=%s）", subject, type(exc).__name__)
        return "pending", [_VECTOR_WARNING]


def prepare_knowledge(db: Session, document, pages=None) -> dict:
    """只生成本地片段；调用方提交后再同步远程向量，避免长期占用 SQLite 写锁。"""
    passages = _ensure_passages(db, document, pages)
    return {"passage_count": len(passages), "vector_status": "pending" if rag_milvus.configured() else "disabled",
            "warnings": []}


def sync_knowledge(db: Session, document_id: int) -> dict:
    """只向 Milvus 同步已经提交的资料；不替调用方提交任何业务事务。"""
    if _has_uncommitted_knowledge(db):
        raise ValueError("请先提交教学资料，再同步 Milvus 向量索引。")
    document = db.get(SubjectKnowledgeChunk, document_id)
    if document is None:
        raise ValueError("教学资料不存在。")
    passages = db.query(SubjectKnowledgePassage).filter_by(document_id=document_id).order_by(
        SubjectKnowledgePassage.chunk_index, SubjectKnowledgePassage.id,
    ).all()
    vector_status, warnings = _sync_vectors(document.subject, _vector_records(document, passages))
    return {"passage_count": len(passages), "vector_status": vector_status, "warnings": warnings}


def index_knowledge(db: Session, document, pages=None) -> dict:
    """兼容旧入口；新资料仅准备片段，提交后应显式调用 sync_knowledge。"""
    result = prepare_knowledge(db, document, pages)
    if not rag_milvus.configured():
        return result
    if _has_uncommitted_knowledge(db):
        result["warnings"] = ["本地片段尚未提交；提交资料后请同步 Milvus 向量索引。"]
        return result
    return sync_knowledge(db, document.id)


def reindex_subject(db: Session, subject: str) -> dict:
    """重建单一学科索引；拒绝提交调用方 Session 中其他未完成的写事务。"""
    if _has_uncommitted_session_writes(db):
        raise ValueError("请先提交或回滚当前 Session 的数据库修改，再重建学科索引。")
    documents = db.query(SubjectKnowledgeChunk).filter_by(subject=subject).order_by(SubjectKnowledgeChunk.id).all()
    records = []
    for document in documents:
        records.extend(_vector_records(document, _ensure_passages(db, document)))
    # 远程嵌入按批次执行，不能让整个过程占用 SQLite 唯一写事务。
    db.commit()
    vector_status, warnings = _sync_vectors(subject, records)
    return {"documents": len(documents), "passage_count": len(records),
            "vector_status": vector_status, "warnings": warnings}


def delete_knowledge_index(db: Session, document_id: int) -> list[int]:
    """捕获即将删除的片段 ID；提交本地删除后仅清理这批确切的远程 ID。"""
    passage_ids = [row[0] for row in db.query(SubjectKnowledgePassage.id).filter_by(
        document_id=document_id,
    ).order_by(SubjectKnowledgePassage.id).all()]
    db.query(SubjectKnowledgePassage).filter_by(document_id=document_id).delete(synchronize_session=False)
    return passage_ids


def delete_vector_index(passage_ids: list[int]) -> list[str]:
    """只删除旧片段向量，避免复用的文档 ID 让延迟清理误删新资料。"""
    if passage_ids and rag_milvus.configured():
        try:
            rag_milvus.delete_passages(passage_ids)
        except Exception as exc:
            logger.warning("移除向量索引失败（passage_count=%s, error=%s）", len(passage_ids), type(exc).__name__)
            return ["资料已移除；Milvus 中的旧索引暂未清理，检索会忽略这些已删除资料。"]
    return []


def _load_candidates(db: Session, subject: str) -> list[dict]:
    documents = db.query(SubjectKnowledgeChunk).filter_by(subject=subject).order_by(SubjectKnowledgeChunk.id).all()
    if not documents:
        return []
    rows = db.query(SubjectKnowledgePassage).join(
        SubjectKnowledgeChunk, SubjectKnowledgeChunk.id == SubjectKnowledgePassage.document_id,
    ).filter(SubjectKnowledgeChunk.subject == subject).order_by(SubjectKnowledgePassage.id).all()
    by_document = defaultdict(list)
    for row in rows:
        by_document[row.document_id].append(row)
    candidates = []
    for document in documents:
        passages = by_document.get(document.id)
        if passages:
            records = [{"passage_id": row.id, "document_id": document.id,
                        "parent_index": row.parent_index, "chunk_index": row.chunk_index,
                        "content": row.content, "parent_content": row.parent_content,
                        "page_number": row.page_number} for row in passages]
        else:
            # 历史资料立即可检索；读请求不写库，也不批量调用远程嵌入接口。
            records = [{"passage_id": None, **record} for record in _passage_data(document)]
        for record in records:
            record.update(title=document.title, source_name=document.source_name)
            candidates.append(record)
    return candidates


def _bm25_rank(
    candidates: list[dict], query_tokens: set[str], single_cjk_token: str | None = None,
) -> list[tuple[int, float]]:
    counters = [Counter(
        _tokenize(item["title"], single_cjk_token)
        * 2 + _tokenize(item["content"], single_cjk_token)
    ) for item in candidates]
    lengths = [sum(counter.values()) for counter in counters]
    average = sum(lengths) / max(len(lengths), 1) or 1
    frequencies = Counter(token for counter in counters for token in counter if token in query_tokens)
    ranked = []
    for index, counter in enumerate(counters):
        score = 0.0
        # 单独共享一个题目数值不能说明两段材料相关，例如 2+2 不应命中“面积除以2”。
        overlap = query_tokens & counter.keys()
        if not any(not token.replace(".", "", 1).isdigit() for token in overlap):
            continue
        for token in overlap:
            count = counter[token]
            idf = math.log(1 + (len(counters) - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
            score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * lengths[index] / average))
        if score > 0:
            ranked.append((index, score))
    return sorted(ranked, key=lambda entry: (-entry[1], entry[0]))


def search_knowledge(db: Session, subject: str, query: str, limit: int = 4) -> dict:
    """分通道排序后做 RRF，恢复父块并去重；score 是排序分而非可信度。"""
    empty = {"items": [], "retrieval_mode": "bm25", "rerank_mode": "local", "warnings": []}
    if not query or not query.strip() or limit <= 0:
        return empty
    query = query.strip()[:2000]
    single_cjk_token = query if (
        len(query) == 1 and "\u4e00" <= query <= "\u9fff"
        and query not in _SINGLE_CJK_STOP_TOKENS
    ) else None
    query_tokens = set(_tokenize(query, single_cjk_token))
    candidates = _load_candidates(db, subject)
    if not candidates:
        return empty
    lexical = _bm25_rank(candidates, query_tokens, single_cjk_token) if query_tokens else []
    scores = defaultdict(float)
    candidate_limit = max(24, min(int(limit), 10) * 6)
    lexical_ranks = {index: rank for rank, (index, _) in enumerate(lexical, 1)}
    lexical_candidates = spread_by_document(
        [index for index, _ in lexical], candidates, candidate_limit,
    )
    for index in lexical_candidates:
        # Candidate spreading changes only who survives the cap; keep each hit's
        # original BM25 rank so a later result does not receive an artificial boost.
        scores[index] += 1 / (_RRF_K + lexical_ranks[index])
    warnings = []
    dense = []
    if rag_milvus.configured():
        try:
            # Long documents can occupy every early vector slot with near-duplicate
            # passages. Overfetch first, then keep a cross-document candidate pool.
            vector_hits = rag_milvus.search_passages(subject, query, min(candidate_limit * 4, 256))
            # Milvus 结果只能对应当前学科、当前仍存在的 SQL 片段；旧/异科 ID 不可用。
            positions = {item["passage_id"]: index for index, item in enumerate(candidates)
                         if item["passage_id"] is not None}
            seen = set()
            dense_ranks = {}
            for passage_id, similarity in vector_hits:
                if passage_id not in positions or passage_id in seen:
                    continue
                if not math.isfinite(similarity) or similarity < (0.45 if lexical else 0.55):
                    continue
                seen.add(passage_id)
                index = positions[passage_id]
                dense_ranks[index] = len(dense_ranks) + 1
            dense_candidates = spread_by_document(
                list(dense_ranks), candidates, candidate_limit,
            )
            for index in dense_candidates:
                dense.append(index)
                scores[index] += 1 / (_RRF_K + dense_ranks[index])
        except Exception as exc:
            logger.warning("Milvus 检索失败（subject=%s, error=%s）", subject, type(exc).__name__)
            warnings.append(_VECTOR_WARNING)
    if not scores:
        return {**empty, "warnings": warnings}

    # 规则重排偏向覆盖题目条件的片段；不把 BM25 原分和余弦相似度直接相加。
    for index in scores:
        tokens = set(_tokenize(candidates[index]["content"], single_cjk_token))
        coverage = len(query_tokens & tokens) / max(len(query_tokens), 1)
        title_coverage = len(query_tokens & set(_tokenize(
            candidates[index]["title"], single_cjk_token,
        ))) / max(len(query_tokens), 1)
        scores[index] += coverage * 0.004 + title_coverage * 0.002
    ranked = sorted(scores, key=lambda index: (-scores[index], index))
    rerank_mode = "local"
    if bailian_rerank.configured():
        try:
            rerank_indices = spread_by_document(
                ranked, candidates, bailian_rerank.MAX_CANDIDATES,
            )
            model_scores = bailian_rerank.rerank_documents(query, [
                f"{candidates[index]['title'][:160]}\n{candidates[index]['content'][:800]}".strip()
                for index in rerank_indices
            ])
            if len(model_scores) != len(rerank_indices) or any(
                isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or not 0.0 <= score <= 1.0
                for score in model_scores
            ):
                raise ValueError("invalid reranker scores")
            # Model scores replace the earlier rank fusion so reranking really
            # controls relevance; do not mix their scale with local RRF scores.
            scores = dict(zip(rerank_indices, model_scores))
            ranked = sorted(rerank_indices, key=lambda index: -scores[index])
            rerank_mode = "model"
        except Exception as exc:
            logger.warning("百炼重排暂不可用，使用本地排序（error=%s）", type(exc).__name__)
            warnings.append(_RERANK_WARNING)
    selected = []
    parent_keys = set()
    parent_texts = set()
    selected_tokens = []
    max_score = max(scores.values()) or 1.0
    while ranked and len(selected) < min(int(limit), 10):
        def diversity_score(index):
            tokens = set(_tokenize(candidates[index]["content"], single_cjk_token))
            similarity = max((len(tokens & other) / max(len(tokens | other), 1)
                              for other in selected_tokens), default=0)
            return 0.85 * scores[index] / max_score - 0.15 * similarity

        index = max(ranked, key=diversity_score)
        ranked.remove(index)
        item = candidates[index]
        parent_key = (item["document_id"], item["page_number"], item["parent_index"])
        parent_text = re.sub(r"\s+", "", item["parent_content"])
        if parent_key in parent_keys or parent_text in parent_texts:
            continue
        parent_keys.add(parent_key)
        parent_texts.add(parent_text)
        selected_tokens.append(set(_tokenize(item["content"])))
        selected.append({
            "document_id": item["document_id"], "title": item["title"],
            "source_name": item["source_name"], "page_number": item["page_number"],
            "passage_id": item["passage_id"], "content": item["parent_content"],
            "score": round(scores[index], 6),
            "citation": f"[资料{item['document_id']}-片段{item['chunk_index'] + 1}]",
        })
    return {"items": selected, "retrieval_mode": "hybrid" if dense else "bm25",
            "rerank_mode": rerank_mode, "warnings": warnings}
