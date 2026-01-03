"""
测试工具函数模块
"""
import os
import json
import unittest
import tempfile

from rss_analyzer.utils import load_articles, save_articles


class TestUtils(unittest.TestCase):
    """工具函数测试"""
    
    def setUp(self):
        """测试前准备"""
        self.test_articles = [
            {"title": "Test 1", "link": "http://test1.com"},
            {"title": "Test 2", "link": "http://test2.com"}
        ]
    
    def test_save_and_load_articles(self):
        """测试保存和加载文章"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        
        try:
            # 保存
            save_articles(self.test_articles, temp_file)
            self.assertTrue(os.path.exists(temp_file))
            
            # 加载
            loaded = load_articles(temp_file)
            self.assertEqual(loaded, self.test_articles)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["title"], "Test 1")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    def test_load_articles_preserves_encoding(self):
        """测试加载文章保持中文编码"""
        articles_with_chinese = [
            {"title": "测试文章", "content": "这是中文内容"}
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        
        try:
            save_articles(articles_with_chinese, temp_file)
            loaded = load_articles(temp_file)
            self.assertEqual(loaded[0]["title"], "测试文章")
            self.assertEqual(loaded[0]["content"], "这是中文内容")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)


if __name__ == "__main__":
    unittest.main()
