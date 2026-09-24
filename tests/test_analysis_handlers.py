import unittest
from unittest.mock import patch

from rss_analyzer.analysis_handlers import (
    ANALYSIS_MESSAGE_HANDLERS,
    handle_analyze_article,
    handle_get_score,
    handle_summarize_article,
)


class TestAnalysisHandlers(unittest.TestCase):
    def test_domain_registry_exposes_article_operations(self):
        self.assertEqual(
            set(ANALYSIS_MESSAGE_HANDLERS),
            {"get_score", "get_scores", "analyze_article", "summarize_article"},
        )

    @patch("rss_analyzer.analysis_handlers.get_cached_score")
    def test_get_score_normalizes_cached_result(self, mock_cached):
        mock_cached.return_value = {
            "score": 4.4,
            "data": {"title": "Cached"},
            "updated_at": "2026-09-24T12:00:00",
        }

        response = handle_get_score({"id": "article-1"})

        self.assertTrue(response["found"])
        self.assertEqual(response["score"], 4.4)
        self.assertEqual(response["data"]["title"], "Cached")

    def test_analyze_article_requires_id(self):
        self.assertEqual(handle_analyze_article({}), {"error": "no_id"})

    @patch("rss_analyzer.analysis_handlers.summarize_single_article")
    def test_summarize_article_reports_provider_failure(self, mock_summarize):
        mock_summarize.return_value = "Summarization failed: timeout"

        response = handle_summarize_article(
            {"id": "article-1", "content": "long content" * 30}
        )

        self.assertEqual(response["error"], "summary_failed")
        self.assertIn("timeout", response["message"])


if __name__ == "__main__":
    unittest.main()
