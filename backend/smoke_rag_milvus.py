"""Milvus adapter contract checks: python smoke_rag_milvus.py.

Uses the installed PyMilvus schema/index builders, with network calls mocked.
Does not connect to Cloudflare, a Milvus server, or any business database.
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
            RAG_MILVUS_COLLECTION="remedi_test", RAG_EMBEDDING_MODEL="@cf/baai/bge-m3",
            RAG_TIMEOUT_SECONDS=2, CLOUDFLARE_ACCOUNT_ID="test-account",
            CLOUDFLARE_API_TOKEN="test-cloudflare-token", create=True,
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
        texts = [f"passage-{index}" for index in range(17)]
        vectors = [[float(index + 1), 0.5, 0.25] for index in range(17)]
        responses = [
            self.response({"success": True, "result": {"data": vectors[:16]}}),
            self.response({"success": True, "result": {"data": vectors[16:]}}),
        ]
        with patch.object(rag.requests, "post", side_effect=responses) as post:
            self.assertEqual(rag.embed_texts(texts), vectors)
        self.assertEqual(post.call_count, 2)
        self.assertEqual([call.kwargs["json"]["text"] for call in post.call_args_list], [texts[:16], texts[16:]])
        self.assertTrue(all(call.kwargs["timeout"] == (2.0, 2.0) for call in post.call_args_list))
        self.assertTrue(post.call_args.args[0].endswith("/ai/run/@cf/baai/bge-m3"))

    def test_embedding_rejects_bad_count_dimensions_and_nonfinite_values(self):
        invalid = (
            [], [[1.0]], [[0.0, 0.0]], [[True, 1.0]], [["1", 2]],
            [[float("nan"), 1.0]], [[float("inf"), 1.0]],
            [[1.0, 2.0], [1.0, 2.0]],
        )
        for vectors in invalid:
            with self.subTest(vectors=vectors), patch.object(
                rag.requests, "post", return_value=self.response({"success": True, "result": {"data": vectors}}),
            ):
                with self.assertRaises(RuntimeError):
                    rag.embed_texts(["one passage"])
        with self.assertRaises(RuntimeError):
            rag._validate_vectors([[1, 2], [1, 2, 3]], expected=2)

    def test_embedding_rejects_dimension_change_across_batches(self):
        responses = [
            self.response({"success": True, "result": {"data": [[1, 2]] * 16}}),
            self.response({"success": True, "result": {"data": [[1, 2, 3]]}}),
        ]
        with patch.object(rag.requests, "post", side_effect=responses), self.assertRaises(RuntimeError):
            rag.embed_texts(["passage"] * 17)

    def test_embedding_errors_do_not_expose_response_or_credentials(self):
        secret = "test-cloudflare-token response-body-private-content"
        with patch.object(rag.requests, "post", side_effect=RuntimeError(secret)):
            with self.assertRaises(RuntimeError) as raised:
                rag.embed_texts(["one passage"])
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        for payload in ({"success": False, "errors": [secret]}, {"success": True, "result": None}):
            with self.subTest(payload=payload), patch.object(rag.requests, "post", return_value=self.response(payload)):
                with self.assertRaises(RuntimeError) as raised:
                    rag.embed_texts(["one passage"])
                self.assertNotIn(secret, str(raised.exception))

    def test_empty_embeddings_and_missing_credentials_never_call_network(self):
        self.assertEqual(rag.embed_texts([]), [])
        with patch.object(rag.settings, "CLOUDFLARE_API_TOKEN", ""), self.assertRaises(RuntimeError):
            rag.embed_texts(["one passage"])
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
        self.assertEqual(request["filter_params"], {"subject": "math", "embedding_model": "@cf/baai/bge-m3"})
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
        self.assertEqual([len(batch) for batch in batches], [16, 16, 3, 16, 16, 3])
        self.assertEqual([row["id"] for batch in batches[:3] for row in batch], list(range(1, 36)))
        self.assertEqual(batches[:3], batches[3:])
        self.assertTrue(all(row["document_id"] == 9 and row["subject"] == "math" and row["embedding_model"] == "@cf/baai/bge-m3" for batch in batches for row in batch))
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
