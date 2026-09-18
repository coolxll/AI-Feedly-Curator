"""
feedly_client 模块单元测试
"""

import unittest
from unittest.mock import patch, MagicMock

from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read


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

    @patch("rss_analyzer.feedly_client.refresh_feedly_config")
    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_refreshes_token_on_401(self, mock_post, mock_config, mock_refresh):
        """测试 401 时自动刷新 token 并重试"""
        mock_config.return_value = {
            "token": "old_token",
            "refresh_token": "refresh_token",
            "user_id": "user_id",
        }
        mock_refresh.return_value = {
            "token": "new_token",
            "refresh_token": "refresh_token",
            "user_id": "user_id",
        }
        mock_post.side_effect = [
            MagicMock(status_code=401, text="Unauthorized"),
            MagicMock(status_code=200),
        ]

        result = feedly_mark_read("article_id")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(
            mock_post.call_args_list[1].kwargs["headers"]["Authorization"],
            "OAuth new_token",
        )

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_logs_success(self, mock_post, mock_config):
        """测试成功时输出日志"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        with self.assertLogs("rss_analyzer.feedly_client", level="INFO") as cm:
            feedly_mark_read(["id1", "id2"])

        self.assertTrue(any("成功标记 2 篇文章为已读" in log for log in cm.output))


class TestFeedlyFetchUnread(unittest.TestCase):
    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client._request_with_token_refresh")
    def test_fetch_unread_supports_full_unread_pagination(
        self, mock_request, mock_config
    ):
        mock_config.return_value = {"user_id": "u123", "token": "tok"}

        # First page has 1 item and continuation token, second page has 1 item and no continuation
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "items": [{"id": "entry-1", "title": "Post 1"}],
            "continuation": "cont-token-1",
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "items": [{"id": "entry-2", "title": "Post 2"}],
        }
        mock_request.side_effect = [resp1, resp2]

        articles = feedly_fetch_unread(limit=0)

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["id"], "entry-1")
        self.assertEqual(articles[1]["id"], "entry-2")
        self.assertEqual(mock_request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
