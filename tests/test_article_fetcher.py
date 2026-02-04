"""
测试文章抓取模块
"""
import unittest
from unittest.mock import patch, Mock

from rss_analyzer.article_fetcher import fetch_article_content


class TestArticleFetcher(unittest.TestCase):
    """文章抓取测试"""
    
    def test_skip_weixin_links(self):
        """测试跳过微信链接"""
        url = "https://weixin.sogou.com/article/123"
        result = fetch_article_content(url)
        self.assertIn("微信链接", result)
        self.assertIn("跳过", result)
    
    @patch('rss_analyzer.article_fetcher.requests.get')
    def test_successful_fetch(self, mock_get):
        """测试成功抓取文章"""
        # Mock HTTP 响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body>Test content</body></html>"
        mock_get.return_value = mock_response
        
        # Mock trafilatura - 需要在函数内部 mock
        with patch('trafilatura.extract', return_value="Extracted test content"):
            url = "https://example.com/article"
            result = fetch_article_content(url)
            self.assertEqual(result, "Extracted test content")
        
        mock_get.assert_called_once()
    
    @patch('rss_analyzer.article_fetcher.requests.get')
    def test_http_error(self, mock_get):
        """测试 HTTP 错误"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        url = "https://example.com/notfound"
        result = fetch_article_content(url)
        
        self.assertIn("获取失败", result)
        self.assertIn("404", result)


if __name__ == "__main__":
    unittest.main()
