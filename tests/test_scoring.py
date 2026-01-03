"""
测试评分模块
"""
import unittest
from unittest.mock import patch, Mock

from rss_analyzer.scoring import (
    build_scoring_prompt,
    parse_score_response,
    score_article,
    format_score_result
)


class TestScoring(unittest.TestCase):
    """评分模块测试"""
    
    def test_build_scoring_prompt(self):
        """测试评分提示词构建"""
        prompt = build_scoring_prompt("测试标题", "测试摘要", "测试内容")
        
        self.assertIn("专业内容编辑", prompt)
        self.assertIn("相关性", prompt)
        self.assertIn("信息量与准确性", prompt)
        self.assertIn("测试标题", prompt)
    
    def test_parse_score_response_valid(self):
        """测试解析有效的评分响应"""
        response = """{
            "relevance_score": 4,
            "informativeness_accuracy_score": 5,
            "depth_opinion_score": 3,
            "readability_score": 4,
            "non_redundancy_score": 4,
            "overall_score": 4.0,
            "verdict": "值得阅读",
            "comment": "文章质量不错"
        }"""
        
        result = parse_score_response(response)
        
        self.assertEqual(result["relevance_score"], 4)
        self.assertEqual(result["overall_score"], 4.0)
        self.assertEqual(result["verdict"], "值得阅读")
    
    def test_parse_score_response_invalid(self):
        """测试解析无效响应"""
        result = parse_score_response("这不是JSON")
        
        self.assertEqual(result["overall_score"], 3.0)
        self.assertEqual(result["verdict"], "一般，可选阅读")
    
    def test_format_score_result(self):
        """测试格式化评分结果"""
        score_result = {
            "overall_score": 4.5,
            "verdict": "值得阅读"
        }
        
        formatted = format_score_result(score_result)
        
        self.assertIn("🔥", formatted)
        self.assertIn("值得阅读", formatted)
        self.assertIn("4.5", formatted)
    
    @patch('rss_analyzer.scoring.OpenAI')
    @patch('rss_analyzer.scoring.PROJ_CONFIG', {"analysis_profile": None})
    def test_score_article_success(self, mock_openai_class):
        """测试成功评分"""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = """{
            "relevance_score": 4,
            "informativeness_accuracy_score": 5,
            "depth_opinion_score": 4,
            "readability_score": 4,
            "non_redundancy_score": 4,
            "overall_score": 4.2,
            "verdict": "值得阅读",
            "comment": "优秀的文章"
        }"""
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        
        mock_client.chat.completions.create.return_value = mock_response
        
        result = score_article("标题", "摘要", "内容")
        
        self.assertEqual(result["overall_score"], 4.2)
        self.assertEqual(result["verdict"], "值得阅读")


if __name__ == "__main__":
    unittest.main()
