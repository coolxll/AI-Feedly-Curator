"""
测试 LLM 分析模块
"""
import unittest
from unittest.mock import patch, Mock

from rss_analyzer.llm_analyzer import analyze_article_with_llm


class TestLLMAnalyzer(unittest.TestCase):
    """LLM 分析测试"""
    
    @patch('rss_analyzer.scoring.score_article')
    def test_analyze_article_success(self, mock_score_article):
        """测试成功分析文章"""
        # Mock score_article 的返回值
        mock_score_article.return_value = {
            "overall_score": 4.5,
            "verdict": "值得阅读",
            "comment": "测试总结",
            "relevance_score": 4,
            "informativeness_accuracy_score": 5,
            "depth_opinion_score": 4,
            "readability_score": 5,
            "non_redundancy_score": 4,
            "article_type": "tutorial",
            "red_flags": []
        }
        
        # 执行测试
        result = analyze_article_with_llm("测试标题", "测试摘要", "测试内容")
        
        # 验证结果
        self.assertEqual(result["score"], 4.5)
        self.assertEqual(result["summary"], "测试总结")
        self.assertEqual(result["detailed_scores"]["relevance"], 4)
        self.assertEqual(result["verdict"], "值得阅读")
    
    @patch('rss_analyzer.scoring.score_article')
    def test_analyze_article_failure(self, mock_score_article):
        """测试分析失败"""
        # Mock 抛出异常
        mock_score_article.side_effect = Exception("API Error")
        
        result = analyze_article_with_llm("标题", "摘要", "内容")
        
        self.assertEqual(result["score"], 0.0)
        self.assertIn("分析失败", result["summary"])


if __name__ == "__main__":
    unittest.main()
