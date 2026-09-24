"""
测试文章抓取模块
"""

import unittest
from unittest.mock import patch, Mock

from rss_analyzer.article_fetcher import (
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


if __name__ == "__main__":
    unittest.main()
