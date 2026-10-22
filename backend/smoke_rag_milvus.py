"""Milvus adapter contract checks: python smoke_rag_milvus.py.

Uses the installed PyMilvus schema/index builders, with network calls mocked.
Does not connect to Bailian, a Milvus server, or any business database.
"""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

from pymilvus import DataType, MilvusClient

from app.services import rag_milvus as rag


class MilvusAdapterTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.multiple(
            rag.settings,
            RAG_MILVUS_URI="http://127.0.0.1:19530", RAG_MILVUS_TOKEN="test-milvus-token",
            RAG_MILVUS_COLLECTION="remedi_test", RAG_EMBEDDING_MODEL="qwen3.7-text-embedding-flash",
            RAG_EMBEDDING_DIMENSIONS=256, RAG_TIMEOUT_SECONDS=2,
            DASHSCOPE_BASE_URL="https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            DASHSCOPE_API_KEY="test-bailian-token", create=True,
        ))
        self.enterContext(patch.object(rag, "_states", {}))
        # A regression must fail the test rather than issue an external call.
        self.enterContext(patch.object(rag.requests, "post", side_effect=AssertionError("unexpected HTTP call")))
        self.enterContext(patch.object(MilvusClient, "__init__", side_effect=AssertionError("unexpected Milvus connection")))

    def response(self, payload):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.json.return_value = payload
        return response

    def embedding_payload(self, vectors, reverse=False):
        data = [{"index": index, "embedding": vector} for index, vector in enumerate(vectors)]
        return {"data": list(reversed(data)) if reverse else data, "model": "qwen3.7-text-embedding-flash"}

    def state(self, existing=False, dimension=3):
        """Fake transport with metadata produced by the real SDK schema builder."""
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="document_id", datatype=DataType.INT64)
        schema.add_field(field_name="subject", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="embedding_model", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="vectors", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        client = Mock()
        client.has_collection.return_value = existing
        client.describe_collection.return_value = schema.to_dict()
        client.prepare_index_params.side_effect = MilvusClient.prepare_index_params
        return rag._ClientState(client, timeout=2)

    def test_embedding_batches_preserve_order_and_bound_timeout(self):
        texts = [f"passage-{index}" for index in range(23)]
        vectors = [[float(index + 1)] + [0.5] * 255 for index in range(23)]
        responses = [self.response(self.embedding_payload(vectors[start:start + 10], reverse=True)) for start in (0, 10, 20)]
        with patch.object(rag.requests, "post", side_effect=responses) as post:
            self.assertEqual(rag.embed_texts(texts), vectors)
        self.assertEqual(post.call_count, 3)
        self.assertEqual([call.kwargs["json"]["input"] for call in post.call_args_list], [texts[:10], texts[10:20], texts[20:]])
        self.assertTrue(all(len(call.kwargs["json"]["input"]) <= 10 for call in post.call_args_list))
        self.assertTrue(all(call.kwargs["timeout"] == (2.0, 2.0) for call in post.call_args_list))
        for request in post.call_args_list:
            self.assertEqual(request.args[0], "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings")
            self.assertEqual(request.kwargs["headers"], {"Authorization": "Bearer test-bailian-token", "Content-Type": "application/json"})
            self.assertEqual(request.kwargs["json"]["model"], "qwen3.7-text-embedding-flash")
            self.assertEqual(request.kwargs["json"]["dimensions"], 256)
            self.assertEqual(request.kwargs["json"]["encoding_format"], "float")
            self.assertFalse(request.kwargs["allow_redirects"])

    def test_embedding_rejects_bad_count_dimensions_and_nonfinite_values(self):
        invalid = (
            [], [[1.0]], [[0.0, 0.0]], [[True, 1.0]], [["1", 2]],
            [[float("nan"), 1.0]], [[float("inf"), 1.0]],
            [[1.0, 2.0], [1.0, 2.0]],
        )
        for vectors in invalid:
            with self.subTest(vectors=vectors), patch.object(
                rag.requests, "post", return_value=self.response(self.embedding_payload(vectors)),
            ):
                with self.assertRaises(RuntimeError):
                    rag.embed_texts(["one passage"])
        with self.assertRaises(RuntimeError):
            rag._validate_vectors([[1, 2], [1, 2, 3]], expected=2)

    def test_embedding_rejects_duplicate_missing_out_of_range_and_noninteger_indices(self):
        vector = [0.5] * 256
        invalid = (
            [{"index": 0, "embedding": vector}, {"index": 0, "embedding": vector}],
            [{"index": 0, "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"index": 2, "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"index": -1, "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"index": "1", "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"index": 1.0, "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"index": True, "embedding": vector}],
            [{"index": 0, "embedding": vector}, {"embedding": vector}],
            [{"index": 0, "embedding": vector}, None],
        )
        for data in invalid:
            with self.subTest(data=data), patch.object(rag.requests, "post", return_value=self.response({"data": data})):
                with self.assertRaises(RuntimeError):
                    rag.embed_texts(["first", "second"])

    def test_embedding_rejects_dimension_change_across_batches(self):
        responses = [
            self.response(self.embedding_payload([[0.5] * 256] * 10)),
            self.response(self.embedding_payload([[0.5] * 255])),
        ]
        with patch.object(rag.requests, "post", side_effect=responses), self.assertRaises(RuntimeError):
            rag.embed_texts(["passage"] * 11)

    def test_embedding_errors_do_not_expose_response_or_credentials(self):
        secret = "test-bailian-token response-body-private-content"
        with patch.object(rag.requests, "post", side_effect=RuntimeError(secret)):
            with self.assertRaises(RuntimeError) as raised:
                rag.embed_texts(["one passage"])
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        for payload in ({"error": {"message": secret}}, {"data": None}):
            with self.subTest(payload=payload), patch.object(rag.requests, "post", return_value=self.response(payload)):
                with self.assertRaises(RuntimeError) as raised:
                    rag.embed_texts(["one passage"])
                self.assertNotIn(secret, str(raised.exception))

    def test_empty_embeddings_and_missing_credentials_never_call_network(self):
        self.assertEqual(rag.embed_texts([]), [])
        with patch.object(rag.settings, "DASHSCOPE_API_KEY", ""):
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                rag.embed_texts(["one passage"])
            with patch.object(rag, "_client_state") as client_state, self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                rag.upsert_passages("math", [{"id": 1, "document_id": 1, "title": "Title", "content": "Text"}])
            client_state.assert_not_called()
        rag.requests.post.assert_not_called()

    def test_embedding_uses_configured_dimensions_for_both_query_and_documents(self):
        state = self.state(dimension=256)
        state.client.search.return_value = [[]]
        response = self.response(self.embedding_payload([[0.5] * 256]))
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")), patch.object(
            rag.requests, "post", return_value=response,
        ) as post:
            rag.upsert_passages("math", [{"id": 1, "document_id": 1, "title": "Title", "content": "Text"}])
            rag.search_passages("math", "Question")
        self.assertEqual(post.call_count, 2)
        self.assertTrue(all(call.kwargs["json"]["dimensions"] == 256 for call in post.call_args_list))
        self.assertEqual(len(state.client.upsert.call_args.kwargs["data"][0]["vectors"]), 256)
        self.assertEqual(len(state.client.search.call_args.kwargs["data"][0]), 256)

    def test_embedding_rejects_invalid_configuration_without_network(self):
        for dimension in (0, 1, 64, 255, 2048, True, "1024", float("nan"), 32769):
            with self.subTest(dimension=dimension), patch.object(rag.settings, "RAG_EMBEDDING_DIMENSIONS", dimension):
                with self.assertRaises(RuntimeError):
                    rag.embed_texts(["passage"])
        for url in ("", "file:///tmp/model", "https://user:password@example.com/v1", "https://example.com/v1?secret=hidden"):
            with self.subTest(url=url), patch.object(rag.settings, "DASHSCOPE_BASE_URL", url), self.assertRaises(RuntimeError):
                rag.embed_texts(["passage"])
        rag.requests.post.assert_not_called()

    def test_real_sdk_schema_and_index_are_created_once_under_concurrency(self):
        state = self.state()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: rag._ensure_collection(state, "remedi_test", 3), range(24)))
        state.client.create_collection.assert_called_once()
        state.client.load_collection.assert_called_once()
        state.client.has_collection.assert_called_once()
        request = state.client.create_collection.call_args.kwargs
        schema = request["schema"].to_dict()
        fields = {item["name"]: item for item in schema["fields"]}
        self.assertFalse(schema["auto_id"])
        self.assertFalse(schema["enable_dynamic_field"])
        self.assertEqual(set(fields), {"id", "document_id", "subject", "embedding_model", "vectors"})
        self.assertEqual(fields["id"]["type"], DataType.INT64)
        self.assertTrue(fields["id"]["is_primary"])
        self.assertEqual(fields["document_id"]["type"], DataType.INT64)
        self.assertEqual(fields["vectors"]["type"], DataType.FLOAT_VECTOR)
        self.assertEqual(fields["vectors"]["params"]["dim"], 3)
        self.assertEqual(fields["subject"]["params"]["max_length"], 32)
        self.assertEqual(fields["embedding_model"]["params"]["max_length"], 256)
        index = list(request["index_params"])[0].to_dict()
        self.assertEqual((index["field_name"], index["index_type"], index["metric_type"]), ("vectors", "AUTOINDEX", "COSINE"))
        self.assertEqual(request["consistency_level"], "Strong")
        self.assertEqual(request["timeout"], 2)

    def test_existing_collection_dimension_mismatch_is_rejected(self):
        state = self.state(existing=True, dimension=4)
        with self.assertRaises(RuntimeError):
            rag._ensure_collection(state, "remedi_test", dimension=3)
        self.assertNotIn("remedi_test", state.ready)
        state.client.create_collection.assert_not_called()
        state.client.load_collection.assert_not_called()
        cached = self.state()
        cached.ready["remedi_test"] = 4
        with self.assertRaises(RuntimeError):
            rag._ensure_collection(cached, "remedi_test", dimension=3)
        cached.client.has_collection.assert_not_called()

    def test_client_state_is_reused_and_local_vector_files_are_rejected(self):
        state = self.state()
        key = (rag.settings.RAG_MILVUS_URI, rag.settings.RAG_MILVUS_TOKEN, 2.0)
        rag._states[key] = state
        self.assertIs(rag._client_state()[0], state)
        self.assertIs(rag._client_state()[0], state)
        for uri in ("./local.db", "file:///tmp/vectors.db", ""):
            with self.subTest(uri=uri), patch.object(rag.settings, "RAG_MILVUS_URI", uri), self.assertRaises(RuntimeError):
                rag._client_state()
        with patch.object(rag.settings, "RAG_MILVUS_URI", ""):
            self.assertFalse(rag.configured())

    def test_search_filters_subject_and_model_and_ignores_nonfinite_scores(self):
        state = self.state(existing=True)
        state.client.search.return_value = [[
            {"id": 7, "distance": 0.94}, {"id": 8, "distance": float("nan")},
        ]]
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")), patch.object(
            rag, "embed_texts", return_value=[[1, 2, 3]],
        ):
            self.assertEqual(rag.search_passages("math", "question", limit=999), [(7, 0.94)])
        request = state.client.search.call_args.kwargs
        self.assertEqual(request["filter"], "subject == {subject} and embedding_model == {embedding_model}")
        self.assertEqual(request["filter_params"], {"subject": "math", "embedding_model": "qwen3.7-text-embedding-flash"})
        self.assertEqual(request["anns_field"], "vectors")
        self.assertEqual(request["search_params"]["metric_type"], "COSINE")
        self.assertEqual(request["limit"], 256)
        self.assertEqual(request["timeout"], 2)

    def test_upsert_batches_keep_stable_ids_and_document_metadata(self):
        state = self.state()
        passages = [{"id": index + 1, "document_id": 9, "title": "Lesson", "content": f"Passage {index}"} for index in range(35)]
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")), patch.object(
            rag, "embed_texts", side_effect=lambda texts: [[1, 2, 3] for _ in texts],
        ) as embed:
            rag.upsert_passages("math", passages)
            rag.upsert_passages("math", passages)
        batches = [call.kwargs["data"] for call in state.client.upsert.call_args_list]
        self.assertEqual([len(batch) for batch in batches], [10, 10, 10, 5, 10, 10, 10, 5])
        self.assertEqual([row["id"] for batch in batches[:4] for row in batch], list(range(1, 36)))
        self.assertEqual(batches[:4], batches[4:])
        self.assertTrue(all(row["document_id"] == 9 and row["subject"] == "math" and row["embedding_model"] == "qwen3.7-text-embedding-flash" for batch in batches for row in batch))
        self.assertEqual(embed.call_args_list[0].args[0][0], "Lesson\nPassage 0")
        state.client.create_collection.assert_called_once()

    def test_delete_missing_collection_does_not_create_it(self):
        state = self.state()
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")):
            rag.delete_document(9)
            state.client.delete.assert_not_called()
            state.client.has_collection.return_value = True
            rag.delete_document(9)
        self.assertEqual(state.client.delete.call_args.kwargs["filter"], "document_id == 9")
        self.assertEqual(state.client.delete.call_args.kwargs["timeout"], 2)
        state.client.create_collection.assert_not_called()

    def test_passage_cleanup_deletes_only_captured_ids_in_bounded_batches(self):
        state = self.state(existing=True)
        # A new document can reuse document_id=9 while getting a new passage ID.
        vectors = {index: 9 for index in range(1, 302)}

        def delete(**request):
            self.assertNotIn("filter", request)
            for passage_id in request["ids"]:
                vectors.pop(passage_id, None)

        state.client.delete.side_effect = delete
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")):
            rag.delete_passages(list(range(1, 301)) + [1])
        self.assertEqual(vectors, {301: 9})
        batches = [call.kwargs["ids"] for call in state.client.delete.call_args_list]
        self.assertEqual([len(batch) for batch in batches], [256, 44])
        self.assertEqual([value for batch in batches for value in batch], list(range(1, 301)))
        self.assertTrue(all(call.kwargs["timeout"] == 2 for call in state.client.delete.call_args_list))

    def test_empty_or_invalid_passage_cleanup_does_not_connect(self):
        with patch.object(rag, "_client_state") as connect:
            rag.delete_passages([])
            for ids in ([0], [-1], [True], ["1"], [2 ** 63]):
                with self.subTest(ids=ids), self.assertRaises(ValueError):
                    rag.delete_passages(ids)
        connect.assert_not_called()
        state = self.state(existing=False)
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")):
            rag.delete_passages([1])
        state.client.delete.assert_not_called()
        state.client.create_collection.assert_not_called()

    def test_failed_passage_cleanup_sanitizes_errors_and_invalidates_cache(self):
        state = self.state(existing=True)
        state.ready["remedi_test"] = 3
        state.client.delete.side_effect = RuntimeError("test-milvus-token private delete response")
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")), self.assertRaises(RuntimeError) as raised:
            rag.delete_passages([1])
        self.assertNotIn("test-milvus-token", str(raised.exception))
        self.assertNotIn("private delete response", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("remedi_test", state.ready)

    def test_failed_search_invalidates_cached_collection_and_sanitizes_error(self):
        state = self.state(existing=True)
        state.ready["remedi_test"] = 3
        state.client.search.side_effect = RuntimeError("test-milvus-token private remote response")
        with patch.object(rag, "_client_state", return_value=(state, "remedi_test")), patch.object(
            rag, "embed_texts", return_value=[[1, 2, 3]],
        ), self.assertRaises(RuntimeError) as raised:
            rag.search_passages("math", "question")
        self.assertNotIn("test-milvus-token", str(raised.exception))
        self.assertNotIn("private remote response", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("remedi_test", state.ready)


if __name__ == "__main__":
    unittest.main()
