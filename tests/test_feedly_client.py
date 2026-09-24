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
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_chunks_by_default_batch_size(self, mock_post, mock_config):
        """测试按默认 batch_size (100) 自动分批"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        ids = [f"id-{i}" for i in range(250)]
        result = feedly_mark_read(ids)

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(len(mock_post.call_args_list[0].kwargs["json"]["entryIds"]), 100)
        self.assertEqual(len(mock_post.call_args_list[1].kwargs["json"]["entryIds"]), 100)
        self.assertEqual(len(mock_post.call_args_list[2].kwargs["json"]["entryIds"]), 50)

    @patch("rss_analyzer.feedly_client.load_feedly_config")
    @patch("rss_analyzer.feedly_client.requests.post")
    def test_mark_read_custom_batch_size(self, mock_post, mock_config):
        """测试自定义 batch_size 分批"""
        mock_config.return_value = {"token": "test_token"}
        mock_post.return_value = MagicMock(status_code=200)

        ids = ["a", "b", "c", "d", "e"]
        result = feedly_mark_read(ids, batch_size=2)

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_post.call_args_list[0].kwargs["json"]["entryIds"], ["a", "b"])
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["entryIds"], ["c", "d"])
        self.assertEqual(mock_post.call_args_list[2].kwargs["json"]["entryIds"], ["e"])

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


class TestFeedlyRateLimitAndBackoff(unittest.TestCase):
    """测试 429 限流重试与退避机制"""

    def test_calculate_backoff_delay_retry_after(self):
        from rss_analyzer.feedly_client import _calculate_backoff_delay

        resp = MagicMock()
        resp.headers = {"Retry-After": "5"}
        delay = _calculate_backoff_delay(resp, attempt=0)
        self.assertEqual(delay, 5.0)

    def test_calculate_backoff_delay_invalid_retry_after(self):
        from rss_analyzer.feedly_client import _calculate_backoff_delay

        resp = MagicMock()
        resp.headers = {"Retry-After": "not-a-number"}
        delay0 = _calculate_backoff_delay(resp, attempt=0, base_delay=2.0)
        delay1 = _calculate_backoff_delay(resp, attempt=1, base_delay=2.0)
        self.assertEqual(delay0, 2.0)
        self.assertEqual(delay1, 4.0)

    def test_calculate_backoff_delay_capped_at_max(self):
        from rss_analyzer.feedly_client import _calculate_backoff_delay

        resp = MagicMock()
        resp.headers = {}
        delay = _calculate_backoff_delay(resp, attempt=10, base_delay=2.0, max_delay=30.0)
        self.assertEqual(delay, 30.0)

    @patch("rss_analyzer.feedly_client.time.sleep")
    @patch("rss_analyzer.feedly_client.requests.get")
    def test_request_retries_on_429_then_succeeds(self, mock_get, mock_sleep):
        from rss_analyzer.feedly_client import _request_with_token_refresh

        resp_429 = MagicMock(status_code=429, headers={"Retry-After": "3"})
        resp_200 = MagicMock(status_code=200)
        mock_get.side_effect = [resp_429, resp_200]

        config = {"token": "test_token"}
        resp = _request_with_token_refresh("GET", "https://example.com/api", config)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(3.0)

    @patch("rss_analyzer.feedly_client.time.sleep")
    @patch("rss_analyzer.feedly_client.requests.get")
    def test_request_stops_after_max_retries_on_429(self, mock_get, mock_sleep):
        from rss_analyzer.feedly_client import _request_with_token_refresh

        resp_429 = MagicMock(status_code=429, headers={})
        mock_get.return_value = resp_429

        config = {"token": "test_token"}
        resp = _request_with_token_refresh(
            "GET", "https://example.com/api", config, max_rate_limit_retries=2, base_backoff=1.0
        )

        self.assertEqual(resp.status_code, 429)
        # initial + 2 retries = 3 calls
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
