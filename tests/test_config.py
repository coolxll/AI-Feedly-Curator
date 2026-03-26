"""
测试配置模块
"""

import os
import unittest
from unittest.mock import patch

from rss_analyzer.config import OPENAI_DEFAULT_BASE_URL, PROJ_CONFIG, get_config, get_openai_task_config


class TestConfig(unittest.TestCase):
    """配置模块测试"""

    def test_proj_config_defaults(self):
        self.assertEqual(PROJ_CONFIG["limit"], 100)
        self.assertFalse(PROJ_CONFIG["mark_read"])
        self.assertFalse(PROJ_CONFIG["debug"])

    def test_get_config_without_task(self):
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}, clear=True):
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
                result = get_config("TEST_KEY")
                self.assertEqual(result, "test_value")

    def test_get_config_with_task_prefers_dynamic_config(self):
        with patch.dict(os.environ, {"ANALYSIS_OPENAI_MODEL": "env-model"}, clear=True):
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {"ANALYSIS_OPENAI_MODEL": "json-model"}):
                result = get_config("OPENAI_MODEL", task="analysis")
                self.assertEqual(result, "json-model")

    def test_get_config_with_task_falls_back_to_plain_env(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": "default-model"}, clear=True):
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
                result = get_config("OPENAI_MODEL", task="summary")
                self.assertEqual(result, "default-model")

    def test_get_config_default_value(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
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
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
                config = get_openai_task_config("analysis", default_model="fallback-model")
                self.assertEqual(config.api_key, "shared-key")
                self.assertEqual(config.base_url, "https://shared.example/v1")
                self.assertEqual(config.model, "analysis-model")

    def test_get_openai_task_config_uses_defaults_when_values_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
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
            with patch("rss_analyzer.config.USER_DYNAMIC_CONFIG", {}):
                config = get_openai_task_config("summary", default_model="fallback-model")
                self.assertEqual(config.api_key, "shared-key")
                self.assertEqual(config.base_url, "https://shared.example/v1")
                self.assertEqual(config.model, "summary-model")


if __name__ == "__main__":
    unittest.main()
