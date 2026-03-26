"""
测试配置模块
"""

import os
import unittest
from unittest.mock import patch

from rss_analyzer.config import (
    EMBEDDING_DEFAULT_BASE_URL,
    EMBEDDING_DEFAULT_MODEL,
    OPENAI_DEFAULT_BASE_URL,
    PROJ_CONFIG,
    get_config,
    get_embedding_config,
    get_openai_task_config,
)


class TestConfig(unittest.TestCase):
    """配置模块测试"""

    def test_proj_config_defaults(self):
        self.assertEqual(PROJ_CONFIG["limit"], 100)
        self.assertFalse(PROJ_CONFIG["mark_read"])
        self.assertFalse(PROJ_CONFIG["debug"])

    def test_get_config_without_task(self):
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}, clear=True):
            result = get_config("TEST_KEY")
            self.assertEqual(result, "test_value")

    def test_get_config_with_task_falls_back_to_plain_env(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": "default-model"}, clear=True):
            result = get_config("OPENAI_MODEL", task="summary")
            self.assertEqual(result, "default-model")

    def test_get_config_default_value(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_config("NONEXISTENT_KEY", default="fallback")
            self.assertEqual(result, "fallback")

    def test_get_openai_task_config_uses_global_key_base_url_and_task_model(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://shared.example/v1",
                "ANALYSIS_OPENAI_MODEL": "analysis-model",
            },
            clear=True,
        ):
            config = get_openai_task_config("analysis", default_model="fallback-model")
            self.assertEqual(config.api_key, "shared-key")
            self.assertEqual(config.base_url, "https://shared.example/v1")
            self.assertEqual(config.model, "analysis-model")

    def test_get_openai_task_config_uses_defaults_when_values_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            config = get_openai_task_config("summary", default_model="fallback-model")
            self.assertIsNone(config.api_key)
            self.assertEqual(config.base_url, OPENAI_DEFAULT_BASE_URL)
            self.assertEqual(config.model, "fallback-model")

    def test_get_openai_task_config_ignores_task_specific_key_and_base_url(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://shared.example/v1",
                "SUMMARY_OPENAI_API_KEY": "summary-key",
                "SUMMARY_OPENAI_BASE_URL": "https://summary.example/v1",
                "SUMMARY_OPENAI_MODEL": "summary-model",
            },
            clear=True,
        ):
            config = get_openai_task_config("summary", default_model="fallback-model")
            self.assertEqual(config.api_key, "shared-key")
            self.assertEqual(config.base_url, "https://shared.example/v1")
            self.assertEqual(config.model, "summary-model")

    def test_get_embedding_config_prefers_embedding_specific_settings(self):
        with patch.dict(
            os.environ,
            {
                "EMBEDDING_API_KEY": "embedding-key",
                "EMBEDDING_BASE_URL": "https://embedding.example/v1",
                "EMBEDDING_MODEL": "embedding-model",
                "OPENAI_API_KEY": "chat-key",
                "OPENAI_BASE_URL": "https://chat.example/v1",
            },
            clear=True,
        ):
            config = get_embedding_config()
            self.assertEqual(config.api_key, "embedding-key")
            self.assertEqual(config.base_url, "https://embedding.example/v1")
            self.assertEqual(config.model, "embedding-model")

    def test_get_embedding_config_does_not_fall_back_to_openai_base_url(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "shared-key",
                "OPENAI_BASE_URL": "https://chat.example/v1",
            },
            clear=True,
        ):
            config = get_embedding_config()
            self.assertEqual(config.api_key, "shared-key")
            self.assertEqual(config.base_url, EMBEDDING_DEFAULT_BASE_URL)
            self.assertEqual(config.model, EMBEDDING_DEFAULT_MODEL)

    def test_get_embedding_config_supports_legacy_dashscope_env_names(self):
        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "dashscope-key",
                "DASHSCOPE_BASE_URL": "https://dashscope.example/v1",
            },
            clear=True,
        ):
            config = get_embedding_config()
            self.assertEqual(config.api_key, "dashscope-key")
            self.assertEqual(config.base_url, "https://dashscope.example/v1")
            self.assertEqual(config.model, EMBEDDING_DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
