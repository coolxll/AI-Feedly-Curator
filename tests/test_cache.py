import tempfile
import unittest
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from rss_analyzer import cache
from rss_analyzer.cache import build_vector_store_payload


class TestCacheVectorPayload(unittest.TestCase):
    def test_build_vector_store_payload_prefers_summary(self):
        payload = build_vector_store_payload(
            "article-1",
            4.5,
            {
                "title": "Test Title",
                "summary": "Summary text",
                "content": "Longer raw content",
                "url": "https://example.com/article",
            },
            "2026-03-26T12:00:00",
        )

        self.assertEqual(payload["article_id"], "article-1")
        self.assertIn("Title: Test Title", payload["document_text"])
        self.assertIn("Content: Summary text", payload["document_text"])
        self.assertNotIn("Longer raw content", payload["document_text"])
        self.assertEqual(payload["metadata"]["score"], 4.5)
        self.assertEqual(payload["metadata"]["url"], "https://example.com/article")
        self.assertEqual(payload["metadata"]["updated_at"], "2026-03-26T12:00:00")

    def test_build_vector_store_payload_returns_none_without_title_or_text(self):
        payload = build_vector_store_payload(
            "article-2",
            3.2,
            {},
        )
        self.assertIsNone(payload)


class TestVersionedScoreCache(unittest.TestCase):
    def test_cache_requires_matching_analysis_and_content_fingerprints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "scores.db")
            with (
                patch.object(cache, "DB_PATH", db_path),
                patch.object(cache, "is_vector_store_enabled", return_value=False),
            ):
                cache.init_db()
                cache.save_cached_score(
                    "article-1",
                    4.2,
                    {
                        "status": "success",
                        "score": 4.2,
                        "analysis_fingerprint": "policy-a",
                        "content_hash": "content-a",
                    },
                )

                self.assertIsNotNone(
                    cache.get_cached_score(
                        "article-1",
                        analysis_fingerprint="policy-a",
                        content_hash="content-a",
                    )
                )
                self.assertIsNone(
                    cache.get_cached_score(
                        "article-1",
                        analysis_fingerprint="policy-b",
                        content_hash="content-a",
                    )
                )
                self.assertIsNone(
                    cache.get_cached_score(
                        "article-1",
                        analysis_fingerprint="policy-a",
                        content_hash="content-b",
                    )
                )

    def test_vector_outbox_retries_failed_index_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "scores.db")
            fake_vector_store = Mock()
            fake_vector_store.add_article.side_effect = [False, True]
            fake_module = SimpleNamespace(vector_store=fake_vector_store)
            with (
                patch.object(cache, "DB_PATH", db_path),
                patch.object(cache, "is_vector_store_enabled", return_value=True),
                patch.object(cache, "start_vector_index_worker"),
                patch.object(cache._VECTOR_WORKER_EVENT, "set"),
                patch.dict(sys.modules, {"rss_analyzer.vector_store": fake_module}),
            ):
                cache.init_db()
                cache.save_cached_score(
                    "article-1",
                    4.0,
                    {"title": "Title", "summary": "Body"},
                )
                self.assertEqual(cache.get_vector_index_queue_stats()["pending"], 1)

                first = cache.process_vector_index_queue(limit=1)
                self.assertEqual(first["failed"], 1)
                self.assertEqual(first["total"], 1)

                retry = cache.retry_vector_index_queue()
                self.assertEqual(retry["retried"], 1)
                second = cache.process_vector_index_queue(limit=1)
                self.assertEqual(second["processed"], 1)
                self.assertEqual(second["total"], 0)


if __name__ == "__main__":
    unittest.main()
