import os
import subprocess
import tempfile
import unittest
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from rss_analyzer import cache
from rss_analyzer.cache import build_vector_store_payload

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    def test_default_db_path_resolves_to_project_root_from_tmp_cwd(self):
        env = dict(os.environ)
        env.pop("RSS_SCORES_DB", None)
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from rss_analyzer import cache; print(cache.DB_PATH); print(cache.get_db_path())",
            ],
            cwd="/tmp",
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        expected = str(PROJECT_ROOT / "rss_scores.db")
        self.assertEqual(lines[-2], expected)
        self.assertEqual(lines[-1], expected)

    def test_get_db_path_honors_post_import_env_override_and_monkeypatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_db = str(Path(temp_dir) / "env_scores.db")
            patched_db = str(Path(temp_dir) / "patched_scores.db")
            with patch.dict(os.environ, {"RSS_SCORES_DB": env_db}, clear=False):
                self.assertEqual(cache.get_db_path(), env_db)
                with patch.object(cache, "DB_PATH", patched_db):
                    self.assertEqual(cache.get_db_path(), patched_db)

    def test_connect_closes_connection_and_sets_wal_and_busy_timeout(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "connect_test.db")
            with patch.object(cache, "DB_PATH", db_path):
                with cache._connect() as conn:
                    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                    busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                    self.assertEqual(journal_mode.lower(), "wal")
                    self.assertEqual(busy_timeout, 30000)

                # Connection must be closed after exiting context manager
                with self.assertRaises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")

    def test_vector_worker_survives_transient_exception(self):
        import sqlite3

        class _StopLoop(BaseException):
            pass

        wait_calls = 0

        def fake_wait(timeout=None):
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls > 2:
                raise _StopLoop()
            return True

        with (
            patch.object(cache._VECTOR_WORKER_EVENT, "wait", side_effect=fake_wait),
            patch.object(cache._VECTOR_WORKER_EVENT, "clear"),
            patch.object(cache, "is_vector_store_enabled", return_value=True),
            patch.object(
                cache,
                "process_vector_index_queue",
                side_effect=[
                    sqlite3.OperationalError("database is locked"),
                    {"pending": 0, "processed": 1, "failed": 0},
                ],
            ) as mock_process,
            patch("rss_analyzer.cache.time.sleep") as mock_sleep,
        ):
            with self.assertRaises(_StopLoop):
                cache._vector_worker()

        self.assertEqual(mock_process.call_count, 2)
        mock_sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
