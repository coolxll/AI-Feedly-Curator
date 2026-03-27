import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rss_analyzer.vector_store import ChromaVectorStore


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


if __name__ == "__main__":
    unittest.main()
