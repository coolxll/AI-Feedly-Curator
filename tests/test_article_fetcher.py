"""
测试文章抓取模块
"""

import os
import unittest
from unittest.mock import patch, Mock

from rss_analyzer.article_fetcher import (
    _truncate_content,
    fetch_article_content,
    fetch_articles_content_concurrently,
)


class TestArticleFetcher(unittest.TestCase):
    """文章抓取测试"""

    def test_skip_weixin_links(self):
        """测试跳过微信链接"""
        url = "https://weixin.sogou.com/article/123"
        result = fetch_article_content(url)
        self.assertIn("微信链接", result)
        self.assertIn("跳过", result)

    @patch("rss_analyzer.article_fetcher.requests.get")
    def test_successful_fetch(self, mock_get):
        """测试成功抓取文章"""
        # Mock HTTP 响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body>Test content</body></html>"
        mock_get.return_value = mock_response

        # Mock trafilatura - 需要在函数内部 mock
        with patch("trafilatura.extract", return_value="Extracted test content"):
            url = "https://example.com/article"
            result = fetch_article_content(url)
            self.assertEqual(result, "Extracted test content")

    @patch("rss_analyzer.article_fetcher.requests.get")
    def test_fetch_applies_configured_cap(self, mock_get):
        """The extract path must route through the configurable cap.

        Regression guard for the hard-coded `result[:10000]`: this asserts the
        call site honours RSS_MAX_CONTENT_CHARS, which the helper-level tests
        alone would not catch.
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body>x</body></html>"
        mock_get.return_value = mock_response

        long_body = "y" * 30000
        with patch.dict(os.environ, {"RSS_MAX_CONTENT_CHARS": "15000"}, clear=True):
            with patch("trafilatura.extract", return_value=long_body):
                with self.assertLogs(
                    "rss_analyzer.article_fetcher", level="WARNING"
                ):
                    result = fetch_article_content("https://example.com/long")
        self.assertEqual(len(result), 15000)

    @patch("rss_analyzer.article_fetcher.requests.get")
    def test_fetch_keeps_content_under_default_cap(self, mock_get):
        """A 10354-char article (the reported case) must survive intact."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body>x</body></html>"
        mock_get.return_value = mock_response

        body = "z" * 10354
        with patch.dict(os.environ, {}, clear=True):
            with patch("trafilatura.extract", return_value=body):
                result = fetch_article_content("https://example.com/deep")
        self.assertEqual(len(result), 10354)
        self.assertEqual(result, body)

        mock_get.assert_called_once()

    @patch("rss_analyzer.article_fetcher.requests.get")
    def test_http_error(self, mock_get):
        """测试 HTTP 错误"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        url = "https://example.com/notfound"
        result = fetch_article_content(url)

        self.assertIn("获取失败", result)
        self.assertIn("404", result)

    def test_concurrent_fetch_empty_and_falsy(self):
        """测试空列表或空字符串并发抓取"""
        self.assertEqual(fetch_articles_content_concurrently([]), {})
        self.assertEqual(fetch_articles_content_concurrently(["", ""]), {})

    def test_concurrent_fetch_success_and_deduplication(self):
        """测试并发抓取成功及 URL 去重"""
        mock_fetch = Mock(side_effect=lambda u: f"Content for {u}")
        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/1",
        ]
        results = fetch_articles_content_concurrently(urls, max_workers=2, fetch_one=mock_fetch)

        self.assertEqual(len(results), 2)
        self.assertEqual(results["https://example.com/1"], "Content for https://example.com/1")
        self.assertEqual(results["https://example.com/2"], "Content for https://example.com/2")
        self.assertEqual(mock_fetch.call_count, 2)

    def test_concurrent_fetch_exception_handling(self):
        """测试并发抓取中单个任务异常不影响整体"""
        def faulty_fetch(url: str) -> str:
            if "fail" in url:
                raise RuntimeError("Network boom")
            return "Good content"

        urls = ["https://example.com/ok", "https://example.com/fail"]
        results = fetch_articles_content_concurrently(urls, max_workers=2, fetch_one=faulty_fetch)

        self.assertEqual(results["https://example.com/ok"], "Good content")
        self.assertIn("处理异常", results["https://example.com/fail"])
        self.assertIn("Network boom", results["https://example.com/fail"])


class TestContentTruncation(unittest.TestCase):
    """Truncation must be configurable and must warn when it drops content.

    Regression guard: a hard-coded `result[:10000]` silently dropped the tail
    of long-form articles before LLM scoring/summarization.
    """

    def test_short_content_is_untouched(self):
        text = "x" * 500
        with patch.dict(
            os.environ, {"RSS_MAX_CONTENT_CHARS": "1000"}, clear=True
        ):
            self.assertEqual(_truncate_content(text, "http://u"), text)

    def test_long_content_is_capped(self):
        text = "x" * 5000
        with patch.dict(
            os.environ, {"RSS_MAX_CONTENT_CHARS": "1000"}, clear=True
        ):
            with self.assertLogs("rss_analyzer.article_fetcher", level="WARNING") as cm:
                out = _truncate_content(text, "http://example.com/a")
        self.assertEqual(len(out), 1000)
        joined = "\n".join(cm.output)
        self.assertIn("truncated", joined)
        self.assertIn("5000", joined)  # original length is reported
        self.assertIn("http://example.com/a", joined)  # url is reported

    def test_zero_means_no_limit(self):
        text = "x" * 5000
        with patch.dict(os.environ, {"RSS_MAX_CONTENT_CHARS": "0"}, clear=True):
            self.assertEqual(len(_truncate_content(text, "http://u")), 5000)

    def test_negative_means_no_limit(self):
        text = "x" * 5000
        with patch.dict(os.environ, {"RSS_MAX_CONTENT_CHARS": "-1"}, clear=True):
            self.assertEqual(len(_truncate_content(text, "http://u")), 5000)

    def test_default_limit_covers_previously_truncated_length(self):
        """A 10354-char article (the case that exposed the bug) must pass intact
        under the default limit."""
        text = "x" * 10354
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(len(_truncate_content(text, "http://u")), 10354)


if __name__ == "__main__":
    unittest.main()
