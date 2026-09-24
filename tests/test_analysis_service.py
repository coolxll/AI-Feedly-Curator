import unittest
from unittest.mock import Mock, patch

from rss_analyzer.analysis_service import ArticleAnalysisService, PreparedArticle


class TestArticleAnalysisService(unittest.TestCase):
    def setUp(self):
        self.cache_get = Mock(return_value=None)
        self.cache_save = Mock()
        self.analyze_one = Mock(
            return_value={"status": "success", "score": 4.1, "summary": "Useful"}
        )
        self.analyze_batch = Mock()
        self.service = ArticleAnalysisService(
            fetch_content=Mock(return_value="fetched body"),
            analyze_one=self.analyze_one,
            analyze_batch=self.analyze_batch,
            cache_get=self.cache_get,
            cache_save=self.cache_save,
        )
        self.article = PreparedArticle(
            article_id="article-1",
            title="Title",
            url="https://example.com/article",
            summary="Summary",
            content="Content",
        )

    @patch("rss_analyzer.analysis_service.build_analysis_fingerprint", return_value="policy")
    @patch("rss_analyzer.analysis_service.build_content_hash", return_value="content")
    def test_valid_cache_is_reused(self, mock_content_hash, mock_fingerprint):
        cached_data = {"status": "success", "score": 3.8, "summary": "Cached"}
        self.cache_get.return_value = {"score": 3.8, "data": cached_data}

        result = self.service.analyze_prepared(self.article)

        self.assertEqual(result, cached_data)
        self.cache_get.assert_called_once_with(
            "article-1",
            analysis_fingerprint="policy",
            content_hash="content",
        )
        self.analyze_one.assert_not_called()
        self.cache_save.assert_not_called()

    @patch("rss_analyzer.analysis_service.build_analysis_fingerprint", return_value="policy")
    @patch("rss_analyzer.analysis_service.build_content_hash", return_value="content")
    def test_cache_miss_is_analyzed_with_version_metadata(
        self, mock_content_hash, mock_fingerprint
    ):
        result = self.service.analyze_prepared(self.article)

        self.assertEqual(result["analysis_fingerprint"], "policy")
        self.assertEqual(result["content_hash"], "content")
        self.assertEqual(result["title"], "Title")
        self.analyze_one.assert_called_once_with("Title", "Summary", "Content")
        self.cache_save.assert_called_once_with("article-1", 4.1, result)

    @patch("rss_analyzer.analysis_service.build_analysis_fingerprint", return_value="policy")
    @patch("rss_analyzer.analysis_service.build_content_hash")
    def test_batch_preserves_cached_and_uncached_input_order(
        self, mock_content_hash, mock_fingerprint
    ):
        second = PreparedArticle("article-2", "Second", "", "", "Second body")
        mock_content_hash.side_effect = ["first-hash", "second-hash"]
        self.cache_get.side_effect = [
            {"score": 3.5, "data": {"status": "success", "score": 3.5, "title": "First"}},
            None,
        ]
        self.analyze_batch.return_value = [
            {"status": "success", "score": 4.4, "summary": "New"}
        ]

        results = self.service.analyze_many_prepared([self.article, second])

        self.assertEqual([result["score"] for result in results], [3.5, 4.4])
        self.analyze_batch.assert_called_once_with(
            [{"title": "Second", "summary": "", "content": "Second body"}]
        )
        self.cache_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
