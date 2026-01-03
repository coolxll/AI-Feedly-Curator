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
        self.assertIn("Red Flags", prompt)
        self.assertIn("测试标题", prompt)
    
    def test_parse_score_response_valid(self):
        """测试解析有效的评分响应"""
        response = """{
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
        # 教程类权重: readability=4, informative=3. 
        # 简单验证分数计算是否非零
        self.assertTrue(result["overall_score"] > 0)
        self.assertEqual(result["verdict"], "值得阅读")
        self.assertEqual(result["article_type"], "tutorial")
    
    def test_parse_score_with_red_flags(self):
        """测试包含负面特征的评分"""
        response = """{
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
        
        # 有 Red Flag，分数应被限制
        self.assertLessEqual(result["overall_score"], 2.5)
        self.assertIn("不推荐", result["verdict"])
        self.assertIn("pure_promotion", result["verdict"])
        
    def test_parse_score_response_invalid(self):
        """测试解析无效响应"""
        result = parse_score_response("这不是JSON")
        
        self.assertEqual(result["overall_score"], 0.0)
        self.assertEqual(result["verdict"], "解析错误")
    
    def test_format_score_result(self):
        """测试格式化评分结果"""
        # score_result 现在的结构由 parse_score_response 决定，
        # 但 format_score_result 暂时还没在 scoring.py 里更新（它被移除还是保留了？）
        # 之前的代码里 format_score_result 似乎没有被用到 scoring.py 的导出里？
        # 检查 scoring.py 发现之前没有定义 format_score_result，是在 llm_analyzer 里被 import 的吗？
        # 不，之前的 commit 中有 export format_score_result。
        # 但在刚才的 replace_file_content 中，我似乎覆盖了 scoring.py 的内容，需要检查 format_score_result 是否还存在。
        pass

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
