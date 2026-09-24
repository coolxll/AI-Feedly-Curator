import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from rss_analyzer import feedly_auth


class TestFeedlyAuth(unittest.TestCase):
    def test_resolve_config_prefers_environment_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "feedly.json"
            config_path.write_text("{}", encoding="utf-8")

            with patch.dict(
                "os.environ", {"FEEDLY_CONFIG_PATH": str(config_path)}, clear=False
            ):
                self.assertEqual(
                    feedly_auth.resolve_feedly_config_file(), str(config_path)
                )

    def test_resolve_config_honors_new_environment_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "new-feedly.json"

            with patch.dict(
                "os.environ", {"FEEDLY_CONFIG_PATH": str(config_path)}, clear=False
            ):
                self.assertEqual(
                    feedly_auth.resolve_feedly_config_file(), str(config_path)
                )

    def test_load_and_save_config_use_explicit_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "feedly.json"
            feedly_auth.save_feedly_config(
                {"token": "token-value", "label": "中文"}, config_path
            )

            loaded = feedly_auth.load_feedly_config(config_path)

            self.assertEqual(loaded, {"token": "token-value", "label": "中文"})
            self.assertIn("中文", config_path.read_text(encoding="utf-8"))

    def test_apply_token_data_preserves_rotating_refresh_token(self):
        original = {"refresh_token": "old-refresh", "custom": "keep"}

        updated = feedly_auth.apply_token_data(
            original,
            {"access_token": "new-access", "expires_in": 60},
            now=100,
        )

        self.assertEqual(updated["token"], "new-access")
        self.assertEqual(updated["refresh_token"], "old-refresh")
        self.assertEqual(updated["token_expires_at"], 160)
        self.assertEqual(updated["custom"], "keep")
        self.assertNotIn("token", original)

    @patch("rss_analyzer.feedly_auth.get_feedly_proxy", return_value=None)
    @patch("rss_analyzer.feedly_auth.requests.post")
    def test_refresh_uses_web_session_response_without_fallback(
        self, mock_post, mock_proxy
    ):
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": "new-access"}
        mock_post.return_value = response

        result = feedly_auth.refresh_access_token("refresh-value")

        self.assertEqual(result["access_token"], "new-access")
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["data"]["client_id"], "feedly")

    @patch("rss_analyzer.feedly_auth.get_feedly_proxy", return_value=None)
    @patch("rss_analyzer.feedly_auth.requests.post")
    def test_refresh_falls_back_to_pkce_client(self, mock_post, mock_proxy):
        web_response = MagicMock(status_code=400)
        pkce_response = MagicMock(status_code=200)
        pkce_response.json.return_value = {"access_token": "pkce-access"}
        mock_post.side_effect = [web_response, pkce_response]

        result = feedly_auth.refresh_access_token("refresh-value")

        self.assertEqual(result["access_token"], "pkce-access")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(
            mock_post.call_args_list[1].kwargs["data"]["client_id"], "feedlydev"
        )
        pkce_response.raise_for_status.assert_called_once_with()

    @patch("rss_analyzer.feedly_auth.get_feedly_proxy", return_value=None)
    @patch("rss_analyzer.feedly_auth.requests.post")
    def test_refresh_falls_back_after_network_error(self, mock_post, mock_proxy):
        pkce_response = MagicMock(status_code=200)
        pkce_response.json.return_value = {"access_token": "pkce-access"}
        mock_post.side_effect = [requests.ConnectionError("offline"), pkce_response]

        result = feedly_auth.refresh_access_token("refresh-value")

        self.assertEqual(result["access_token"], "pkce-access")
        self.assertEqual(mock_post.call_count, 2)

    def test_refresh_config_persists_shared_token_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "feedly.json"
            original = {
                "token": "old-access",
                "refresh_token": "old-refresh",
                "user_id": "user-1",
            }
            config_path.write_text(json.dumps(original), encoding="utf-8")

            with patch(
                "rss_analyzer.feedly_auth.refresh_access_token",
                return_value={"access_token": "new-access", "expires_in": 120},
            ):
                updated = feedly_auth.refresh_feedly_config(original, config_path)

            self.assertEqual(updated["token"], "new-access")
            self.assertEqual(updated["refresh_token"], "old-refresh")
            self.assertIs(updated, original)
            self.assertEqual(original["token"], "new-access")
            self.assertEqual(
                feedly_auth.load_feedly_config(config_path)["token"], "new-access"
            )


if __name__ == "__main__":
    unittest.main()
