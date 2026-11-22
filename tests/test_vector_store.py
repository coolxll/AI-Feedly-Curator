import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rss_analyzer.vector_store import ChromaVectorStore, DashScopeEmbeddingFunction


class FakeCollection:
    def __init__(self, count: int):
        self._count = count

    def count(self):
        return self._count


class TestVectorStoreEmbeddingFingerprint(unittest.TestCase):
    def build_store(self, count: int = 0) -> ChromaVectorStore:
        store = ChromaVectorStore.__new__(ChromaVectorStore)
        store.backend = "embedded"
        store.collection_name = "unit_test_articles"
        store.persist_dir = "unused"
        store.state_dir = "unused-state"
        store.http_host = "127.0.0.1"
        store.http_port = 8000
        store.http_ssl = False
        store.http_url = "http://127.0.0.1:8000"
        store.fingerprint_path = "unused.json"
        store.collection = FakeCollection(count)
        return store

    def build_embedding_fn(self, base_url: str, model_name: str):
        return SimpleNamespace(base_url=base_url, model_name=model_name)

    def test_ensure_embedding_fingerprint_writes_on_first_init(self):
        store = self.build_store(count=0)
        embedding_fn = self.build_embedding_fn(
            "https://embedding.example/v1", "embedding-model"
        )

        with patch.object(store, "_load_embedding_fingerprint", return_value=None):
            with patch.object(store, "_write_embedding_fingerprint") as mock_write:
                store._ensure_embedding_fingerprint(embedding_fn)

        fingerprint = mock_write.call_args.args[0]
        self.assertEqual(fingerprint["model"], "embedding-model")
        self.assertEqual(fingerprint["base_url"], "https://embedding.example/v1")
        self.assertTrue(fingerprint["fingerprint"])

    def test_ensure_embedding_fingerprint_warns_on_mismatch_with_existing_vectors(self):
        store = self.build_store(count=3)
        embedding_fn = self.build_embedding_fn(
            "https://embedding-b.example/v1", "embedding-model-b"
        )
        existing = {
            "fingerprint": "old-fingerprint",
            "model": "embedding-model-a",
            "base_url": "https://embedding-a.example/v1",
        }

        with patch.object(store, "_load_embedding_fingerprint", return_value=existing):
            with patch.object(store, "_write_embedding_fingerprint") as mock_write:
                with patch("rss_analyzer.vector_store.logger.warning") as mock_warning:
                    store._ensure_embedding_fingerprint(embedding_fn)

        mock_write.assert_not_called()
        self.assertTrue(mock_warning.called)

    def test_ensure_embedding_fingerprint_updates_when_collection_is_empty(self):
        store = self.build_store(count=0)
        embedding_fn = self.build_embedding_fn(
            "https://embedding-b.example/v1", "embedding-model-b"
        )
        existing = {
            "fingerprint": "old-fingerprint",
            "model": "embedding-model-a",
            "base_url": "https://embedding-a.example/v1",
        }

        with patch.object(store, "_load_embedding_fingerprint", return_value=existing):
            with patch.object(store, "_write_embedding_fingerprint") as mock_write:
                store._ensure_embedding_fingerprint(embedding_fn)

        fingerprint = mock_write.call_args.args[0]
        self.assertEqual(fingerprint["model"], "embedding-model-b")
        self.assertEqual(fingerprint["base_url"], "https://embedding-b.example/v1")


class TestDashScopeEmbeddingFunction(unittest.TestCase):
    @patch("rss_analyzer.vector_store.OpenAI")
    def test_openai_client_includes_user_agent_header(self, mock_openai):
        with patch.dict(
            os.environ,
            {
                "EMBEDDING_API_KEY": "embedding-key",
                "EMBEDDING_BASE_URL": "https://embedding.example/v1",
                "EMBEDDING_USER_AGENT": "EmbeddingUA/1.0",
            },
            clear=True,
        ):
            embedding_fn = DashScopeEmbeddingFunction()

        mock_openai.assert_called_once_with(
            api_key="embedding-key",
            base_url="https://embedding.example/v1",
            default_headers={"User-Agent": "EmbeddingUA/1.0"},
        )
        self.assertIsNotNone(embedding_fn.client)

    @patch("rss_analyzer.vector_store.OpenAI")
    def test_call_sorts_out_of_order_embeddings_by_index(self, mock_openai):
        mock_client = Mock()
        mock_client.embeddings.create.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(index=2, embedding=[0.3]),
                SimpleNamespace(index=0, embedding=[0.1]),
                SimpleNamespace(index=1, embedding=[0.2]),
            ]
        )
        mock_openai.return_value = mock_client

        with patch.dict(os.environ, {"EMBEDDING_API_KEY": "k"}, clear=True):
            embedding_fn = DashScopeEmbeddingFunction()
            vectors = embedding_fn(["a", "b", "c"])

        self.assertEqual([round(float(v[0]), 2) for v in vectors], [0.1, 0.2, 0.3])


class TestVectorStoreRecovery(unittest.TestCase):
    def build_store(self, persist_dir: str = "unused") -> ChromaVectorStore:
        store = ChromaVectorStore.__new__(ChromaVectorStore)
        store.backend = "embedded"
        store.collection_name = "unit_test_articles"
        store.persist_dir = persist_dir
        store.state_dir = "unused-state"
        store.http_host = "127.0.0.1"
        store.http_port = 8000
        store.http_ssl = False
        store.http_url = "http://127.0.0.1:8000"
        store.fingerprint_path = os.path.join(
            persist_dir, "unit_test_articles_embedding_fingerprint.json"
        )
        store.client = None
        store.collection = None
        return store

    def test_validate_existing_store_returns_false_on_failed_subprocess(self):
        store = self.build_store()
        failed = subprocess.CompletedProcess(
            args=["python"], returncode=1, stdout="", stderr="access violation"
        )

        with patch("rss_analyzer.vector_store.subprocess.run", return_value=failed):
            with patch("rss_analyzer.vector_store.logger.warning") as mock_warning:
                healthy = store._validate_existing_store()

        self.assertFalse(healthy)
        self.assertTrue(mock_warning.called)

    def test_quarantine_persist_dir_moves_existing_directory(self):
        store = self.build_store("C:\\tmp\\chroma_db")

        with patch("rss_analyzer.vector_store.os.replace") as mock_replace:
            with patch("rss_analyzer.vector_store.os.makedirs") as mock_makedirs:
                backup_dir = store._quarantine_persist_dir()

        self.assertIn("_quarantine_", backup_dir)
        mock_replace.assert_called_once_with(store.persist_dir, backup_dir)
        mock_makedirs.assert_called_once_with(store.persist_dir, exist_ok=True)

    @patch.object(ChromaVectorStore, "_ensure_embedding_fingerprint")
    @patch("rss_analyzer.vector_store.DashScopeEmbeddingFunction")
    @patch("rss_analyzer.vector_store.chromadb")
    def test_initialize_quarantines_unhealthy_store_before_recreating_collection(
        self, mock_chromadb, mock_embedding_cls, mock_fingerprint
    ):
        fake_client = Mock()
        fake_collection = Mock()
        fake_client.get_or_create_collection.return_value = fake_collection
        mock_chromadb.PersistentClient.return_value = fake_client
        mock_embedding_cls.return_value = SimpleNamespace(
            base_url="https://embedding.example/v1", model_name="embedding-model"
        )

        persist_dir = "C:\\tmp\\chroma_db"
        store = self.build_store(persist_dir)
        store._trending_cache = None
        store._trending_cache_time = None

        with patch.object(ChromaVectorStore, "_has_persisted_store", return_value=True):
            with patch.object(
                ChromaVectorStore, "_validate_existing_store", return_value=False
            ):
                with patch.object(
                    ChromaVectorStore,
                    "_quarantine_persist_dir",
                    return_value=f"{persist_dir}_quarantine_20260327_090000",
                ) as mock_quarantine:
                    store._initialize()

        mock_quarantine.assert_called_once()
        mock_chromadb.PersistentClient.assert_called_with(path=persist_dir)
        fake_client.get_or_create_collection.assert_called()
        self.assertIs(store.collection, fake_collection)

    @patch.object(ChromaVectorStore, "_ensure_embedding_fingerprint")
    @patch("rss_analyzer.vector_store.DashScopeEmbeddingFunction")
    @patch("rss_analyzer.vector_store.chromadb")
    def test_initialize_uses_http_client_when_backend_is_http(
        self, mock_chromadb, mock_embedding_cls, mock_fingerprint
    ):
        fake_client = Mock()
        fake_collection = Mock()
        fake_client.get_or_create_collection.return_value = fake_collection
        mock_chromadb.HttpClient.return_value = fake_client
        mock_embedding_cls.return_value = SimpleNamespace(
            base_url="https://embedding.example/v1", model_name="embedding-model"
        )

        store = self.build_store("unused")
        store.backend = "http"
        store.state_dir = "vector_store_state"
        store.fingerprint_path = os.path.join(
            store.state_dir, "unit_test_articles_embedding_fingerprint.json"
        )

        store._initialize()

        mock_chromadb.HttpClient.assert_called_once_with(
            host="127.0.0.1",
            port=8000,
            ssl=False,
        )
        fake_client.get_or_create_collection.assert_called_once_with(
            name="unit_test_articles"
        )
        self.assertIs(store.collection, fake_collection)

    def test_add_article_uses_explicit_embeddings_for_http_backend(self):
        store = self.build_store("unused")
        store.backend = "http"
        store.collection = Mock()
        store.embedding_fn = Mock(return_value=[[0.1, 0.2]])

        success = store.add_article("article-1", "hello world", {"score": 4.0})

        self.assertTrue(success)
        store.collection.upsert.assert_called_once_with(
            ids=["article-1"],
            documents=["hello world"],
            metadatas=[{"score": 4.0}],
            embeddings=[[0.1, 0.2]],
        )

    def test_search_similar_uses_query_embeddings_for_http_backend(self):
        store = self.build_store("unused")
        store.backend = "http"
        store.collection = Mock()
        store.embedding_fn = Mock(return_value=[[0.3, 0.4]])
        store.collection.query.return_value = {
            "ids": [["article-1"]],
            "documents": [["hello world"]],
            "metadatas": [[{"score": 4.0}]],
            "distances": [[0.12]],
        }

        results = store.search_similar("hello", limit=2)

        self.assertEqual(len(results), 1)
        store.collection.query.assert_called_once_with(
            query_embeddings=[[0.3, 0.4]],
            n_results=2,
        )

    def test_add_articles_uses_batch_embeddings_for_http_backend(self):
        store = self.build_store("unused")
        store.backend = "http"
        store.collection = Mock()
        store.embedding_fn = Mock(return_value=[[0.1, 0.2], [0.3, 0.4]])

        result = store.add_articles(
            [
                {
                    "article_id": "article-1",
                    "document_text": "doc one",
                    "metadata": {"score": 4.0},
                },
                {
                    "article_id": "article-2",
                    "document_text": "doc two",
                    "metadata": {"score": 3.5},
                },
            ]
        )

        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failed_ids"], [])
        store.collection.upsert.assert_called_once_with(
            ids=["article-1", "article-2"],
            documents=["doc one", "doc two"],
            metadatas=[{"score": 4.0}, {"score": 3.5}],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
        )

    def test_cleanup_invalid_entries_omits_ids_from_include_and_handles_none_values(self):
        store = self.build_store("unused")
        store.collection = Mock()
        store.collection.get.return_value = {
            "ids": ["id-none", "id-blank", "id-short-none-meta", "id-valid"],
            "documents": [None, "   ", "tiny", "This is a valid document body."],
            "metadatas": [None, {}, None, {"title": "Valid"}],
        }

        removed = store.cleanup_invalid_entries()

        store.collection.get.assert_called_once_with(include=["documents", "metadatas"])
        store.collection.delete.assert_called_once_with(
            ids=["id-none", "id-blank", "id-short-none-meta"]
        )
        self.assertEqual(removed, 3)

    def test_clear_collection_recreates_collection_via_client_delete_collection(self):
        store = self.build_store("unused")
        store.backend = "embedded"
        store.embedding_fn = Mock()
        new_collection = Mock()
        store.client = Mock()
        store.client.get_or_create_collection.return_value = new_collection
        store.collection = Mock()

        result = store.clear_collection()

        self.assertTrue(result)
        store.client.delete_collection.assert_called_once_with(
            name="unit_test_articles"
        )
        store.client.get_or_create_collection.assert_called_once_with(
            name="unit_test_articles",
            embedding_function=store.embedding_fn,
        )
        self.assertIs(store.collection, new_collection)

    def test_clear_collection_falls_back_to_deleting_ids_when_client_lacks_delete_collection(self):
        store = self.build_store("unused")
        store.client = SimpleNamespace()
        store.collection = Mock()
        store.collection.get.return_value = {"ids": ["a1", "a2"]}

        result = store.clear_collection()

        self.assertTrue(result)
        store.collection.get.assert_called_once_with(include=[])
        store.collection.delete.assert_called_once_with(ids=["a1", "a2"])

    @patch("rss_analyzer.vector_store.DashScopeEmbeddingFunction")
    def test_refresh_embedding_fingerprint_updates_embedding_fn_and_collection(
        self, mock_embedding_cls
    ):
        store = self.build_store("unused")
        store.backend = "embedded"
        old_fn = Mock()
        new_fn = SimpleNamespace(
            base_url="https://embedding-new.example/v1", model_name="new-model"
        )
        mock_embedding_cls.return_value = new_fn
        recreated_collection = Mock()
        recreated_collection.count.return_value = 0
        store.client = Mock()
        store.client.get_or_create_collection.return_value = recreated_collection
        store.collection = Mock()
        store.embedding_fn = old_fn

        with (
            patch.object(store, "_load_embedding_fingerprint", return_value=None),
            patch.object(store, "_write_embedding_fingerprint") as mock_write,
        ):
            ok = store.refresh_embedding_fingerprint()

        self.assertTrue(ok)
        self.assertIs(store.embedding_fn, new_fn)
        self.assertIs(store.collection, recreated_collection)
        store.client.get_or_create_collection.assert_called_once_with(
            name="unit_test_articles",
            embedding_function=new_fn,
        )
        mock_write.assert_called_once()

    def test_delete_articles_empty_list_returns_true_without_calling_collection(self):
        store = self.build_store("unused")
        store.collection = Mock()
        self.assertTrue(store.delete_articles([]))
        store.collection.delete.assert_not_called()

    def test_normalize_metadata_skips_none_values(self):
        store = self.build_store("unused")
        normalized = store._normalize_metadata({"title": "T", "score": None, "ok": True})
        self.assertEqual(normalized, {"title": "T", "ok": True})
        self.assertNotIn("score", normalized)

    def test_search_similar_guards_limit_clamps_fetch_and_handles_bad_metadata(self):
        store = self.build_store("unused")
        store.collection = Mock()
        store.collection.count.return_value = 3
        store.collection.query.return_value = {
            "ids": [["a1", "a2", "a3"]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[None, {"score": "None"}, {"score": 2.0}]],
            "distances": [[0.1, 0.2, 0.3]],
        }

        self.assertEqual(store.search_similar("q", limit=0), [])
        store.collection.query.assert_not_called()

        results = store.search_similar("q", limit=5, min_score=3.0)
        # fetch_limit should be clamped to collection.count() == 3
        self.assertEqual(store.collection.query.call_args.kwargs["n_results"], 3)
        # a1 (None metadata) and a2 ("None" score) don't crash; a3 (score 2.0 < 3.0) is filtered out
        self.assertEqual([r["id"] for r in results], ["a1", "a2"])

    def test_discover_trending_topics_guards_none_metadata_and_caps_sample_size(self):
        from datetime import datetime

        store = self.build_store("unused")
        now_iso = datetime.now().isoformat()
        store.collection = Mock()
        store.collection.get.return_value = {
            "ids": ["a1", "a2", "a3"],
            "documents": ["python rust", "python go", "python java"],
            "metadatas": [
                {"title": "T1", "updated_at": now_iso},
                None,
                {"title": "T3", "updated_at": now_iso},
            ],
        }
        seen_ids = []

        def fake_tags(article_id, _text):
            seen_ids.append(article_id)
            return ["python"]

        with (
            patch("rss_analyzer.cache.get_app_cache", return_value=None),
            patch("rss_analyzer.cache.set_app_cache"),
            patch.object(store, "get_article_tags", side_effect=fake_tags),
        ):
            trending = store.discover_trending_topics(limit=5, sample_size=1, hours=24)

        self.assertEqual(len(seen_ids), 1)
        self.assertEqual(trending[0]["topic"], "Python")

    def test_quarantine_persist_dir_strips_trailing_slash(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            chroma_dir = os.path.join(tmpdir, "chroma_db")
            os.makedirs(chroma_dir)
            store = self.build_store(chroma_dir + os.sep)
            backup_dir = store._quarantine_persist_dir()
            self.assertTrue(backup_dir.startswith(f"{chroma_dir}_quarantine_"))
            self.assertTrue(os.path.isdir(backup_dir))
            self.assertTrue(os.path.isdir(chroma_dir))


if __name__ == "__main__":
    unittest.main()
