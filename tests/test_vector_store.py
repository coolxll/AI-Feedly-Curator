import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rss_analyzer.vector_store import ChromaVectorStore


class FakeCollection:
    def __init__(self, count: int):
        self._count = count

    def count(self):
        return self._count


class TestVectorStoreEmbeddingFingerprint(unittest.TestCase):
    def build_store(self, count: int = 0) -> ChromaVectorStore:
        store = ChromaVectorStore.__new__(ChromaVectorStore)
        store.collection_name = "unit_test_articles"
        store.persist_dir = "unused"
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


if __name__ == "__main__":
    unittest.main()
