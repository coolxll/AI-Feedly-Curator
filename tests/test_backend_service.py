import unittest
from unittest.mock import patch

from rss_analyzer.backend_service import get_runtime_paths, handle_message


class TestBackendService(unittest.TestCase):
    def test_health_message_exposes_runtime_paths(self):
        response = handle_message({"type": "health"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["service"], "rss-backend")
        runtime = get_runtime_paths()
        self.assertEqual(response["db_path"], runtime["db_path"])
        self.assertEqual(response["vector_db_dir"], runtime["vector_db_dir"])

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.analyze_articles_with_llm_batch")
    def test_get_scores_prefers_cached_results(self, mock_batch, mock_cached_score):
        mock_cached_score.return_value = {
            "score": 4.2,
            "data": {"title": "Cached title", "summary": "Cached summary"},
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "get_scores",
                "items": [{"id": "article-1", "title": "Ignored title"}],
            }
        )

        self.assertIn("article-1", response["items"])
        self.assertTrue(response["items"]["article-1"]["found"])
        self.assertEqual(response["items"]["article-1"]["score"], 4.2)
        mock_batch.assert_not_called()

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.save_cached_score")
    @patch("rss_analyzer.backend_service.summarize_single_article")
    def test_summarize_article_updates_cache(self, mock_summarize, mock_save, mock_cached):
        mock_summarize.return_value = "summary body"
        mock_cached.return_value = {
            "score": 3.9,
            "data": {"title": "Existing title"},
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "summarize_article",
                "id": "article-2",
                "title": "New title",
                "url": "https://example.com/article",
                "content": "Long enough content" * 20,
            }
        )

        self.assertEqual(response["summary"], "summary body")
        mock_summarize.assert_called_once_with("Long enough content" * 20, task="summary")
        mock_save.assert_called_once()
        _, _, saved_data = mock_save.call_args.args
        self.assertEqual(saved_data["summary"], "summary body")
        self.assertEqual(saved_data["url"], "https://example.com/article")

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.save_cached_score")
    @patch("rss_analyzer.backend_service.summarize_single_article")
    def test_summarize_article_returns_error_without_caching_on_failure(
        self, mock_summarize, mock_save, mock_cached
    ):
        mock_summarize.return_value = "Summarization failed: invalid model"
        mock_cached.return_value = {
            "score": 3.9,
            "data": {"title": "Existing title"},
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "summarize_article",
                "id": "article-3",
                "title": "Title",
                "content": "Long enough content" * 20,
            }
        )

        self.assertEqual(response["error"], "summary_failed")
        self.assertIn("invalid model", response["message"])
        mock_save.assert_not_called()

    def test_unknown_message_type(self):
        response = handle_message({"type": "does_not_exist"})
        self.assertEqual(response, {"error": "unknown_type"})


if __name__ == "__main__":
    unittest.main()
