"""
测试配置模块
"""
import os
import unittest
from unittest.mock import patch

from rss_analyzer.config import get_config, PROJ_CONFIG


class TestConfig(unittest.TestCase):
    """配置模块测试"""
    
    def test_proj_config_defaults(self):
        """测试默认配置"""
        self.assertEqual(PROJ_CONFIG["limit"], 100)
        self.assertFalse(PROJ_CONFIG["mark_read"])
        self.assertFalse(PROJ_CONFIG["debug"])
    
    def test_get_config_without_profile(self):
        """测试无 profile 时获取配置"""
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}):
            result = get_config("TEST_KEY")
            self.assertEqual(result, "test_value")
    
    def test_get_config_with_profile(self):
        """测试使用 profile 获取配置"""
        with patch.dict(os.environ, {
            "LOCAL_QWEN_OPENAI_API_KEY": "local-key",
            "OPENAI_API_KEY": "default-key"
        }):
            # 使用 profile
            result = get_config("OPENAI_API_KEY", profile="LOCAL_QWEN")
            self.assertEqual(result, "local-key")
            
            # 不使用 profile
            result = get_config("OPENAI_API_KEY")
            self.assertEqual(result, "default-key")
    
    def test_get_config_fallback(self):
        """测试 profile 配置不存在时回退到默认"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "default-key"}, clear=True):
            result = get_config("OPENAI_API_KEY", profile="NONEXISTENT")
            self.assertEqual(result, "default-key")
    
    def test_get_config_default_value(self):
        """测试默认值"""
        result = get_config("NONEXISTENT_KEY", default="fallback")
        self.assertEqual(result, "fallback")


if __name__ == "__main__":
    unittest.main()
