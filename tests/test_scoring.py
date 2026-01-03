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
        
        self.assertIn("判断文章类型", prompt)
        self.assertIn("负面特征", prompt)
        self.assertIn("测试标题", prompt)
    
    def test_parse_score_with_red_flags(self):
        """测试包含负面特征的评分"""
        response = """{
            "analysis": "这显然是一篇软文",
            "article_type": "news",
            "red_flags": ["pure_promotion"],
            "scores": {
                "relevance": 5,
                "informativeness_accuracy": 5,
                "depth_opinion": 5,
                "readability": 5,
                "non_redundancy": 5
            },
            "comment": "虽然分高但是软文"
        }"""
        
        result = parse_score_response(response)
        
        # 有 Red Flag (Hard)，分数应被限制为 1.0
        self.assertEqual(result["overall_score"], 1.0)
        # Verdict 应该是 "不值得读 (含: pure_promotion)"
        self.assertIn("不值得读", result["verdict"])
        self.assertIn("pure_promotion", result["verdict"])

    def test_parse_score_response_valid(self):
        """测试解析有效的评分响应"""
        response = """{
            "analysis": "此文详实。",
            "article_type": "tutorial",
            "red_flags": [],
            "scores": {
                "relevance": 4,
                "informativeness_accuracy": 5,
                "depth_opinion": 3,
                "readability": 4,
                "non_redundancy": 4
            },
            "comment": "文章质量不错"
        }"""
        
        result = parse_score_response(response)
        
        self.assertEqual(result["relevance_score"], 4)
        self.assertTrue(result["overall_score"] > 0)
        self.assertEqual(result["verdict"], "值得阅读")
        self.assertEqual(result["article_type"], "tutorial")

    def test_parse_score_response_invalid(self):
        """测试解析无效响应"""
        result = parse_score_response("这不是JSON")
        
        self.assertEqual(result["overall_score"], 0.0)
        self.assertEqual(result["verdict"], "解析错误")

    @patch('rss_analyzer.scoring.OpenAI')
    @patch('rss_analyzer.scoring.PROJ_CONFIG', {"analysis_profile": None, "scoring_persona": "", "scoring_weights": {}})
    def test_score_article_success(self, mock_openai_class):
        """测试成功评分"""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = """{
            "analysis": "很有深度。",
            "article_type": "opinion",
            "red_flags": [],
            "scores": {
                "relevance": 4,
                "informativeness_accuracy": 4,
                "depth_opinion": 5,
                "readability": 4,
                "non_redundancy": 4
            },
            "comment": "深度好文"
        }"""
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        
        mock_client.chat.completions.create.return_value = mock_response
        
        result = score_article("标题", "摘要", "内容")
        
        self.assertIn("值得阅读", result["verdict"])
        self.assertEqual(result["article_type"], "opinion")


if __name__ == "__main__":
    unittest.main()
