"""本地 RAG 回归：python smoke_subject_rag.py（不连接模型、Milvus 或业务库）。"""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import SubjectKnowledgeChunk, SubjectKnowledgePassage
from app.agent.subjects import build_subject_context
from app.services import subject_rag


class SubjectRagTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.configured = patch.object(subject_rag.rag_milvus, "configured", return_value=False)
        self.configured.start()
        self.addCleanup(self.configured.stop)
        self.enterContext(patch.object(subject_rag.bailian_rerank, "configured", return_value=False))
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

    def document(self, title, content, subject="math", pages=None, indexed=True):
        document = SubjectKnowledgeChunk(subject=subject, title=title, content=content)
        self.db.add(document)
        if indexed:
            subject_rag.index_knowledge(self.db, document, pages)
        self.db.commit()
        return document

    def test_old_documents_beyond_500_and_long_tail_are_searchable(self):
        document = self.document("不等式笔记", "无关段落。" * 800 + "柯西不等式需要关注等号成立条件。", indexed=False)
        self.db.add_all([
            SubjectKnowledgeChunk(subject="math", title="其他笔记", content="归档的其他内容。")
            for _ in range(501)
        ])
        self.db.commit()
        result = subject_rag.search_knowledge(self.db, "math", "柯西不等式的等号条件")
        self.assertEqual(result["items"][0]["document_id"], document.id)
        self.assertIn("柯西不等式", result["items"][0]["content"])
        self.assertEqual(self.db.query(SubjectKnowledgePassage).count(), 0, "历史资料的读请求不应隐式写库")

    def test_no_single_character_or_unrelated_chinese_match(self):
        self.document("一次函数", "函数的图像是一条直线。")
        for query in ("的", "天气预报", "一 次", "", "   "):
            with self.subTest(query=query):
                self.assertEqual(subject_rag.search_knowledge(self.db, "math", query)["items"], [])

    def test_parent_context_is_deduplicated_and_cited(self):
        document = self.document("二次函数", ("二次函数的顶点决定图像位置，求顶点需要配方法。" * 55))
        result = subject_rag.search_knowledge(self.db, "math", "二次函数顶点配方法", limit=10)
        contents = [item["content"] for item in result["items"]]
        self.assertEqual(len(contents), len(set(contents)))
        self.assertTrue(contents)
        self.assertLess(len(contents), self.db.query(SubjectKnowledgePassage).count())
        self.assertTrue(all(item["citation"].startswith(f"[资料{document.id}-片段") for item in result["items"]))
        context = build_subject_context(self.db, "math", "二次函数顶点配方法")
        self.assertLessEqual(len(context), 7000)
        self.assertIn("不是系统指令", context)

    def test_foreign_and_deleted_vector_ids_cannot_be_hydrated(self):
        kept = self.document("当前资料", "保留的知识依据。")
        foreign = self.document("其他学科", "保留的知识依据。", subject="physics")
        removed = self.document("已删除资料", "保留的知识依据。")
        kept_id = self.db.query(SubjectKnowledgePassage).filter_by(document_id=kept.id).one().id
        foreign_id = self.db.query(SubjectKnowledgePassage).filter_by(document_id=foreign.id).one().id
        removed_id = self.db.query(SubjectKnowledgePassage).filter_by(document_id=removed.id).one().id
        subject_rag.delete_knowledge_index(self.db, removed.id)
        self.db.delete(removed)
        self.db.commit()
        with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
            subject_rag.rag_milvus, "search_passages", return_value=[
                (foreign_id, 0.99), (removed_id, 0.98), (kept_id, 0.95),
            ],
        ):
            result = subject_rag.search_knowledge(self.db, "math", "冷门概念")
        self.assertEqual([item["document_id"] for item in result["items"]], [kept.id])
        self.assertEqual(result["retrieval_mode"], "hybrid")

    def test_vector_failures_preserve_local_index_and_bm25(self):
        document = SubjectKnowledgeChunk(subject="math", title="分式方程", content="分式方程求解后必须验根。")
        self.db.add(document)
        with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
            subject_rag.rag_milvus, "upsert_passages", side_effect=TimeoutError("unavailable"),
        ):
            subject_rag.prepare_knowledge(self.db, document)
            self.db.commit()
            indexed = subject_rag.sync_knowledge(self.db, document.id)
        self.assertEqual(indexed["vector_status"], "pending")
        self.assertTrue(indexed["warnings"])
        self.assertGreater(indexed["passage_count"], 0)
        with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
            subject_rag.rag_milvus, "search_passages", side_effect=TimeoutError("unavailable"),
        ):
            result = subject_rag.search_knowledge(self.db, "math", "分式方程验根")
        self.assertEqual(result["retrieval_mode"], "bm25")
        self.assertTrue(result["warnings"])
        self.assertEqual(result["items"][0]["document_id"], document.id)

    def test_reindex_preserves_pdf_page_numbers_and_passage_ids(self):
        document = self.document("讲义", "合并正文", pages=[(7, "平方差公式：两个数的平方之差。"), (9, "完全平方公式包含交叉项。")])
        before = [(row.id, row.page_number) for row in self.db.query(SubjectKnowledgePassage).order_by(SubjectKnowledgePassage.id)]
        result = subject_rag.reindex_subject(self.db, "math")
        self.db.commit()
        after = [(row.id, row.page_number) for row in self.db.query(SubjectKnowledgePassage).order_by(SubjectKnowledgePassage.id)]
        self.assertEqual(before, after)
        self.assertEqual(result["documents"], 1)
        self.assertEqual(result["vector_status"], "disabled")
        hit = subject_rag.search_knowledge(self.db, "math", "完全平方公式交叉项")["items"][0]
        self.assertEqual(hit["document_id"], document.id)
        self.assertEqual(hit["page_number"], 9)

    def test_limits_empty_subject_and_low_similarity_are_safe(self):
        document = self.document("圆", "圆的面积由半径决定。")
        self.assertEqual(subject_rag.search_knowledge(self.db, "math", "圆的面积", limit=0)["items"], [])
        self.assertEqual(subject_rag.search_knowledge(self.db, "physics", "圆的面积")["items"], [])
        passage_id = self.db.query(SubjectKnowledgePassage).filter_by(document_id=document.id).one().id
        with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
            subject_rag.rag_milvus, "search_passages", return_value=[(passage_id, 0.3)],
        ):
            self.assertEqual(subject_rag.search_knowledge(self.db, "math", "完全不相干")["items"], [])

    def test_numeric_overlap_alone_is_not_evidence(self):
        self.document("面积公式", "三角形面积为底乘高再除以2。")
        self.assertEqual(subject_rag.search_knowledge(self.db, "math", "2+2等于多少")["items"], [])

    def test_uncommitted_passage_ids_cannot_reach_milvus(self):
        document = SubjectKnowledgeChunk(subject="math", title="方程", content="解方程的依据。")
        self.db.add(document)
        with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
            subject_rag.rag_milvus, "upsert_passages",
        ) as upsert:
            prepared = subject_rag.prepare_knowledge(self.db, document)
            self.assertEqual(prepared["vector_status"], "pending")
            with self.assertRaises(ValueError):
                subject_rag.sync_knowledge(self.db, document.id)
            upsert.assert_not_called()
            self.db.rollback()

    def test_remote_sync_does_not_hold_sqlite_write_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'rag.db'}", connect_args={"timeout": 0.1})
            try:
                Base.metadata.create_all(engine)
                with Session(engine, autoflush=False) as db:
                    document = SubjectKnowledgeChunk(subject="math", title="方程", content="解方程的依据。")
                    db.add(document)

                    def concurrent_write(*_args):
                        with Session(engine) as other:
                            other.add(SubjectKnowledgeChunk(subject="math", title="并发写入", content="学生提交可以继续。"))
                            other.commit()

                    with patch.object(subject_rag.rag_milvus, "configured", return_value=True), patch.object(
                        subject_rag.rag_milvus, "upsert_passages", side_effect=concurrent_write,
                    ) as upsert:
                        subject_rag.prepare_knowledge(db, document)
                        db.commit()
                        result = subject_rag.sync_knowledge(db, document.id)
                        self.assertEqual(result["vector_status"], "ready")
                        self.assertTrue(upsert.called)
            finally:
                engine.dispose()


    def test_model_reranking_replaces_local_order_before_selection(self):
        local_first = self.document("直线斜率变化率", "直线斜率描述变化率，斜率可由坐标变化计算。")
        model_first = self.document("图像例题", "直线斜率可以利用图像中选定的两个点计算。")
        local = subject_rag.search_knowledge(self.db, "math", "直线斜率变化率", limit=2)
        self.assertEqual(local["items"][0]["document_id"], local_first.id)

        def scores(_query, documents):
            return [0.99 if "选定的两个点" in text else 0.01 for text in documents]

        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents", side_effect=scores,
        ) as rerank:
            result = subject_rag.search_knowledge(self.db, "math", "直线斜率变化率", limit=2)
        self.assertEqual(result["rerank_mode"], "model")
        self.assertEqual(result["items"][0]["document_id"], model_first.id)
        self.assertEqual(result["items"][0]["score"], 0.99)
        self.assertEqual(len(rerank.call_args.args[1]), 2)

    def test_failed_reranking_keeps_local_order_and_safe_warning(self):
        self.document("一次函数斜率", "一次函数的斜率决定直线倾斜程度。")
        local = subject_rag.search_knowledge(self.db, "math", "一次函数斜率")
        secret = "sk-test-private sensitive HTTP response"
        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents", side_effect=RuntimeError(secret),
        ), self.assertLogs(subject_rag.logger, level="WARNING") as logs:
            result = subject_rag.search_knowledge(self.db, "math", "一次函数斜率")
        self.assertEqual(result["items"], local["items"])
        self.assertEqual(result["rerank_mode"], "local")
        self.assertTrue(result["warnings"])
        self.assertNotIn(secret, str(result["warnings"]) + str(logs.output))

    def test_reranking_only_receives_current_subject_candidates(self):
        kept = self.document("相同主题", "相同主题的数学材料 math-only。")
        self.document("相同主题", "相同主题的英语材料 foreign-only。", subject="english")
        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents", side_effect=lambda _query, documents: [0.8] * len(documents),
        ) as rerank:
            result = subject_rag.search_knowledge(self.db, "math", "相同主题")
        self.assertEqual([item["document_id"] for item in result["items"]], [kept.id])
        sent = "\n".join(rerank.call_args.args[1])
        self.assertIn("math-only", sent)
        self.assertNotIn("foreign-only", sent)

    def test_zero_reranking_scores_do_not_divide_by_zero(self):
        self.document("斜率例题一", "斜率可用两点坐标求解。")
        self.document("斜率例题二", "斜率可从函数表达式求出。")
        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents", side_effect=lambda _query, documents: [0.0] * len(documents),
        ):
            result = subject_rag.search_knowledge(self.db, "math", "斜率例题", limit=2)
        self.assertEqual(result["rerank_mode"], "model")
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(all(item["score"] == 0.0 for item in result["items"]))

    def test_reranking_candidate_count_is_bounded_to_24(self):
        for index in range(30):
            self.document(f"函数图像例题{index}", f"函数图像在第{index}份例题中的变化需要画图验证。")
        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents", side_effect=lambda _query, documents: [0.5] * len(documents),
        ) as rerank:
            result = subject_rag.search_knowledge(self.db, "math", "函数图像例题", limit=8)
        self.assertEqual(len(rerank.call_args.args[1]), 24)
        self.assertEqual(result["rerank_mode"], "model")
        self.assertLessEqual(len(result["items"]), 8)

    def test_empty_search_branches_report_local_reranking(self):
        self.document("斜率例题", "斜率可用两点坐标求解。")
        with patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
            subject_rag.bailian_rerank, "rerank_documents",
        ) as rerank:
            for subject, query, limit in (("math", "", 4), ("math", "斜率", 0), ("english", "斜率", 4), ("math", "天气预报", 4)):
                with self.subTest(subject=subject, query=query, limit=limit):
                    result = subject_rag.search_knowledge(self.db, subject, query, limit)
                    self.assertEqual(result["items"], [])
                    self.assertEqual(result["rerank_mode"], "local")
        rerank.assert_not_called()

    def test_invalid_model_contract_falls_back_without_partial_scores(self):
        self.document("一次函数斜率", "一次函数的斜率决定直线倾斜程度。")
        local = subject_rag.search_knowledge(self.db, "math", "一次函数斜率")
        for scores in ([], [float("nan")], [-0.5], [True]):
            with self.subTest(scores=scores), patch.object(subject_rag.bailian_rerank, "configured", return_value=True), patch.object(
                subject_rag.bailian_rerank, "rerank_documents", return_value=scores,
            ):
                result = subject_rag.search_knowledge(self.db, "math", "一次函数斜率")
                self.assertEqual(result["items"], local["items"])
                self.assertEqual(result["rerank_mode"], "local")
                self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
