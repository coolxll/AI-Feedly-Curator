"""
feedly_client 模块单元测试
"""

import unittest
from unittest.mock import patch, MagicMock

from rss_analyzer.feedly_client import feedly_mark_read


class TestFeedlyMarkRead(unittest.TestCase):
    """测试 feedly_mark_read 函数"""

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_single_article(self, mock_post, mock_config):
        """测试标记单篇文章为已读"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        result = feedly_mark_read("article_id_123")

        self.assertTrue(result)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args.kwargs["json"]["entryIds"], ["article_id_123"])

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_multiple_articles(self, mock_post, mock_config):
        """测试批量标记多篇文章为已读"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        ids = ["id1", "id2", "id3"]
        result = feedly_mark_read(ids)

        self.assertTrue(result)
        call_args = mock_post.call_args
        self.assertEqual(call_args.kwargs["json"]["entryIds"], ids)
        self.assertEqual(call_args.kwargs["json"]["action"], "markAsRead")

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    def test_mark_read_no_config(self, mock_config):
        """测试没有配置时返回 False"""
        mock_config.return_value = None

        result = feedly_mark_read("article_id")

        self.assertFalse(result)

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_api_error(self, mock_post, mock_config):
        """测试 API 返回错误时"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")

        result = feedly_mark_read("article_id")

        self.assertFalse(result)

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_logs_success(self, mock_post, mock_config):
        """测试成功时输出日志"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        with self.assertLogs("rss_analyzer.feedly_client", level="INFO") as cm:
            feedly_mark_read(["id1", "id2"])

        self.assertTrue(any("成功标记 2 篇文章为已读" in log for log in cm.output))


if __name__ == "__main__":
    unittest.main()
