"""
测试 LLM 分析模块
"""
import unittest
from unittest.mock import patch, Mock

from rss_analyzer.llm_analyzer import analyze_article_with_llm


class TestLLMAnalyzer(unittest.TestCase):
    """LLM 分析测试"""
    
    @patch('rss_analyzer.llm_analyzer.OpenAI')
    @patch('rss_analyzer.llm_analyzer.PROJ_CONFIG', {"analysis_profile": None})
    def test_analyze_article_success(self, mock_openai_class):
        """测试成功分析文章"""
        # Mock OpenAI 响应
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = '{"score": 8, "summary": "测试摘要", "reason": "测试理由"}'
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        
        mock_client.chat.completions.create.return_value = mock_response
        
        # 执行测试
        result = analyze_article_with_llm("测试标题", "测试摘要", "测试内容")
        
        # 验证结果
        self.assertEqual(result["score"], 8)
        self.assertEqual(result["summary"], "测试摘要")
        self.assertEqual(result["reason"], "测试理由")
    
    @patch('rss_analyzer.llm_analyzer.OpenAI')
    @patch('rss_analyzer.llm_analyzer.PROJ_CONFIG', {"analysis_profile": None})
    def test_analyze_article_empty_response(self, mock_openai_class):
        """测试空响应处理"""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = None
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        
        mock_client.chat.completions.create.return_value = mock_response
        
        result = analyze_article_with_llm("标题", "摘要", "内容")
        
        self.assertEqual(result["score"], 0)
        self.assertIn("失败", result["summary"])


if __name__ == "__main__":
    unittest.main()
