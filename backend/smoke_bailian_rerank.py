"""Bailian reranker contract checks; all HTTP calls are mocked."""
import unittest
from unittest.mock import Mock, patch

from app.services import bailian_rerank as reranker


class BailianRerankTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.multiple(
            reranker.settings,
            DASHSCOPE_API_KEY="test-only-rerank-key",
            DASHSCOPE_BASE_URL="https://llm-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            RAG_RERANK_MODEL="qwen3.7-text-rerank", RAG_RERANK_TIMEOUT_SECONDS=2.5,
            create=True,
        ))
        self.blocked = self.enterContext(patch.object(
            reranker.requests, "post", side_effect=AssertionError("unexpected network access"),
        ))

    def response(self, payload, status=200):
        response = Mock()
        response.status_code = status
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.json.return_value = payload
        return response

    def payload(self, scores):
        return {"output": {"results": [
            {"index": index, "relevance_score": score} for index, score in enumerate(scores)
        ]}}

    def test_native_url_payload_headers_timeout_and_order(self):
        payload = {"output": {"results": [
            {"index": 1, "relevance_score": 0.95}, {"index": 0, "relevance_score": 0.12},
        ]}}
        with patch.object(reranker.requests, "post", return_value=self.response(payload)) as post:
            self.assertEqual(reranker.rerank_documents("问题", ["候选一", "候选二"]), [0.12, 0.95])
        request = post.call_args
        self.assertEqual(request.args[0], "https://llm-test.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank")
        self.assertEqual(request.kwargs["headers"], {"Authorization": "Bearer test-only-rerank-key", "Content-Type": "application/json"})
        self.assertEqual(request.kwargs["json"], {
            "model": "qwen3.7-text-rerank", "input": {"query": "问题", "documents": ["候选一", "候选二"]},
            "parameters": {"top_n": 2},
        })
        self.assertEqual(request.kwargs["timeout"], (2.5, 2.5))
        self.assertFalse(request.kwargs["allow_redirects"])

    def test_legacy_host_keeps_origin_and_drops_compatible_path(self):
        with patch.object(reranker.settings, "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/"), patch.object(
            reranker.requests, "post", return_value=self.response(self.payload([0.8])),
        ) as post:
            self.assertEqual(reranker.rerank_documents("question", ["document"]), [0.8])
        self.assertEqual(post.call_args.args[0], "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank")

    def test_candidate_limit_and_compact_child_payload(self):
        with patch.object(reranker.requests, "post", return_value=self.response(self.payload([0.0] * 24))) as post:
            self.assertEqual(reranker.rerank_documents("问" * 3000, ["文" * 3000] * 24), [0.0] * 24)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["parameters"]["top_n"], 24)
        self.assertLessEqual(len(body["input"]["query"]), 2000)
        self.assertTrue(all(len(text) <= 1000 for text in body["input"]["documents"]))
        with self.assertRaises(ValueError):
            reranker.rerank_documents("question", ["document"] * 25)

    def test_missing_key_or_disabled_model_is_silent_and_offline(self):
        self.assertTrue(reranker.configured())
        with patch.object(reranker.settings, "DASHSCOPE_API_KEY", ""):
            self.assertFalse(reranker.configured())
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                reranker.rerank_documents("question", ["document"])
        with patch.object(reranker.settings, "RAG_RERANK_MODEL", ""):
            self.assertFalse(reranker.configured())
        self.blocked.assert_not_called()

    def test_empty_and_invalid_input_never_call_network(self):
        self.assertEqual(reranker.rerank_documents("question", []), [])
        for query, documents in ((" ", ["doc"]), ("question", [""]), ("question", [None])):
            with self.subTest(query=query, documents=documents), self.assertRaises(ValueError):
                reranker.rerank_documents(query, documents)
        self.blocked.assert_not_called()

    def test_invalid_indices_cannot_reassign_or_omit_a_document(self):
        invalid = (
            [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}],
            [{"index": 0, "relevance_score": 0.5}, {"index": 2, "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, {"index": -1, "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, {"index": True, "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, {"index": "1", "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, {"index": 1.0, "relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, {"relevance_score": 0.6}],
            [{"index": 0, "relevance_score": 0.5}, None],
        )
        for results in invalid:
            with self.subTest(results=results), patch.object(
                reranker.requests, "post", return_value=self.response({"output": {"results": results}}),
            ), self.assertRaises(RuntimeError):
                reranker.rerank_documents("question", ["first", "second"])

    def test_invalid_scores_reject_the_entire_response(self):
        for score in (float("nan"), float("inf"), -0.1, 1.01, True, "0.9", None):
            with self.subTest(score=score), patch.object(
                reranker.requests, "post", return_value=self.response(self.payload([0.5, score])),
            ), self.assertRaises(RuntimeError):
                reranker.rerank_documents("question", ["first", "second"])

    def test_zero_and_one_scores_are_valid_boundaries(self):
        with patch.object(reranker.requests, "post", return_value=self.response(self.payload([0.0, 1.0]))):
            self.assertEqual(reranker.rerank_documents("question", ["first", "second"]), [0.0, 1.0])

    def test_transport_payload_and_redirect_errors_are_sanitized(self):
        secret = "test-only-rerank-key sensitive remote body"
        with patch.object(reranker.requests, "post", side_effect=RuntimeError(secret)), self.assertRaises(RuntimeError) as raised:
            reranker.rerank_documents("question", ["document"])
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        for payload, status in (({"code": secret}, 200), ({"error": secret}, 200), ({"output": None}, 200), (self.payload([0.8]), 302)):
            with self.subTest(status=status, payload=payload), patch.object(
                reranker.requests, "post", return_value=self.response(payload, status),
            ), self.assertRaises(RuntimeError) as raised:
                reranker.rerank_documents("question", ["document"])
            self.assertNotIn(secret, str(raised.exception))

    def test_invalid_configuration_never_calls_network(self):
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), patch.object(
                reranker.settings, "RAG_RERANK_TIMEOUT_SECONDS", timeout,
            ), self.assertRaises(RuntimeError):
                reranker.rerank_documents("question", ["document"])
        for base in ("", "file:///tmp/model", "https://user:secret@example.com/v1", "https://example.com/v1?token=secret"):
            with self.subTest(base=base), patch.object(
                reranker.settings, "DASHSCOPE_BASE_URL", base,
            ), self.assertRaises(RuntimeError):
                reranker.rerank_documents("question", ["document"])
        self.blocked.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
