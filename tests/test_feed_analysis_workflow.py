"""Tests for feed_analysis_workflow concurrent prefetch and analysis."""

import unittest
from unittest.mock import MagicMock, patch

from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.feed_analysis_workflow import analyze_articles


class TestFeedAnalysisWorkflowPrefetch(unittest.TestCase):
    @patch("rss_analyzer.feed_analysis_workflow.generate_summary_report")
    @patch("rss_analyzer.feed_analysis_workflow.save_articles")
    @patch("rss_analyzer.feed_analysis_workflow.load_articles")
    @patch("rss_analyzer.feed_analysis_workflow.os.path.exists", return_value=True)
    def test_concurrent_prefetch_only_needed_unfiltered(
        self,
        mock_exists,
        mock_load_articles,
        mock_save_articles,
        mock_summary,
    ):
        mock_summary.return_value = {
            "summary_file": "output/summary_latest.md",
            "monthly_summary_file": "output/2026-09/summary.md",
            "summary": "all good",
        }
        articles = [
            # 1. Has long content (>200 chars) -> does not need fetch
            {
                "id": "1",
                "title": "Article With Content",
                "content": "A" * 300,
                "summary": "short",
                "link": "https://example.com/has-content",
            },
            # 2. Promotional keyword -> filtered, should not be prefetched
            {
                "id": "2",
                "title": "推广: Buy Now",
                "content": "",
                "summary": "short",
                "link": "https://example.com/promo",
            },
            # 3. Needs fetch
            {
                "id": "3",
                "title": "Tech Deep Dive",
                "content": "",
                "summary": "short",
                "link": "https://example.com/tech-article",
            },
            # 4. Needs fetch
            {
                "id": "4",
                "title": "DevOps Practices",
                "content": "",
                "summary": "short",
                "link": "https://example.com/devops",
            },
        ]
        mock_load_articles.return_value = articles

        fetched_urls = []

        def mock_fetch(url: str) -> str:
            fetched_urls.append(url)
            return "Fetched long content for " + url + " " + ("B" * 200)

        mock_analyze_one = MagicMock(return_value={
            "status": "success",
            "score": 4.5,
            "verdict": "必须阅读",
            "reason": "great",
            "detailed_scores": {
                "relevance": 5.0,
                "informativeness": 4.5,
                "depth": 4.0,
                "readability": 4.0,
                "originality": 4.5,
            },
        })

        with patch("rss_analyzer.feed_analysis_workflow.analyze_article_with_llm", mock_analyze_one):
            with patch.dict(PROJ_CONFIG, {"batch_scoring": False, "filter_keywords": ["推广"]}):
                result = analyze_articles(
                    refresh=False,
                    limit=10,
                    fetch_content=mock_fetch,
                )

        # URLs 3 and 4 should be fetched; URL 1 (has content) and 2 (promo) should not
        self.assertIn("https://example.com/tech-article", fetched_urls)
        self.assertIn("https://example.com/devops", fetched_urls)
        self.assertNotIn("https://example.com/has-content", fetched_urls)
        self.assertNotIn("https://example.com/promo", fetched_urls)

        # 3 articles analyzed (1, 3, 4), 1 skipped (2)
        self.assertEqual(result["successful_count"], 3)
        self.assertEqual(result["processed_count"], 3)

    @patch("rss_analyzer.feed_analysis_workflow.generate_summary_report")
    @patch("rss_analyzer.feed_analysis_workflow.save_articles")
    @patch("rss_analyzer.feed_analysis_workflow.load_articles")
    @patch("rss_analyzer.feed_analysis_workflow.os.path.exists", return_value=True)
    def test_missing_title_and_partial_analysis_result_do_not_crash(
        self,
        mock_exists,
        mock_load_articles,
        mock_save_articles,
        mock_summary,
    ):
        mock_summary.return_value = {
            "summary_file": "output/summary_latest.md",
            "monthly_summary_file": "output/2026-09/summary.md",
            "summary": "ok",
        }
        articles = [
            {
                "id": "no-title-1",
                "content": "A" * 300,
                "summary": "short",
                "link": "https://example.com/no-title",
            },
            {
                "id": "none-title-2",
                "title": None,
                "content": "B" * 300,
                "summary": "short",
                "link": "https://example.com/none-title",
            },
            {
                "id": "partial-detail-3",
                "title": "Partial Detail Article",
                "content": "C" * 300,
                "summary": "short",
                "link": "https://example.com/partial",
            },
        ]
        mock_load_articles.return_value = articles

        side_effects = [
            {
                "status": "success",
                "score": None,
                "verdict": "一般",
                "reason": "missing score and detailed_scores",
                "detailed_scores": None,
            },
            {
                "status": "success",
                "score": "not-a-number",
                "verdict": "一般",
                "reason": "non-dict detailed_scores",
                "detailed_scores": "invalid",
            },
            {
                "status": "success",
                "score": 4.2,
                "verdict": "推荐",
                "reason": "partial sub-keys",
                "detailed_scores": {"relevance": 4.0},
            },
        ]
        mock_analyze_one = MagicMock(side_effect=side_effects)

        with patch("rss_analyzer.feed_analysis_workflow.analyze_article_with_llm", mock_analyze_one):
            with patch.dict(PROJ_CONFIG, {"batch_scoring": False, "filter_keywords": ["推广"]}):
                result = analyze_articles(refresh=False, limit=10)

        self.assertTrue(result["success"])
        self.assertEqual(result["successful_count"], 3)
        self.assertEqual(result["processed_count"], 3)

    @patch("rss_analyzer.feed_analysis_workflow.generate_summary_report")
    @patch("rss_analyzer.feed_analysis_workflow.save_articles")
    @patch("rss_analyzer.feed_analysis_workflow.load_articles")
    @patch("rss_analyzer.feed_analysis_workflow.feedly_fetch_unread")
    @patch("rss_analyzer.feed_analysis_workflow.os.path.exists", return_value=True)
    def test_refresh_true_uses_fresh_articles_even_with_custom_input_file(
        self,
        _mock_exists,
        mock_fetch_unread,
        mock_load_articles,
        mock_save_articles,
        mock_summary,
    ):
        from rss_analyzer.config import LATEST_UNREAD_FILE

        fresh_articles = [
            {
                "id": "fresh-1",
                "title": "Fresh Article",
                "content": "F" * 300,
                "summary": "fresh summary",
                "link": "https://example.com/fresh-1",
            }
        ]
        mock_fetch_unread.return_value = fresh_articles
        mock_load_articles.return_value = fresh_articles
        mock_summary.return_value = {
            "summary_file": "output/summary_latest.md",
            "monthly_summary_file": "output/2026-09/summary.md",
            "summary": "ok",
        }
        mock_analyze_one = MagicMock(return_value={
            "status": "success",
            "score": 4.0,
            "verdict": "推荐",
            "reason": "good",
            "detailed_scores": {"relevance": 4.0},
        })

        with patch("rss_analyzer.feed_analysis_workflow.analyze_article_with_llm", mock_analyze_one):
            with patch.dict(PROJ_CONFIG, {"batch_scoring": False, "filter_keywords": []}):
                result = analyze_articles(
                    input_file="output/custom_old_file.json",
                    refresh=True,
                    limit=5,
                )

        self.assertTrue(result["success"])
        mock_load_articles.assert_called_once_with(LATEST_UNREAD_FILE)


if __name__ == "__main__":
    unittest.main()
