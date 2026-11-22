"""
测试 LLM 分析模块
"""

import unittest
from unittest.mock import patch

from rss_analyzer.llm_analyzer import analyze_article_with_llm


class TestLLMAnalyzer(unittest.TestCase):
    """LLM 分析测试"""

    @patch("rss_analyzer.scoring.score_article")
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
            "red_flags": [],
        }

        # 执行测试
        result = analyze_article_with_llm("测试标题", "测试摘要", "测试内容")

        # 验证结果
        self.assertEqual(result["score"], 4.5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"], "测试总结")
        self.assertEqual(result["detailed_scores"]["relevance"], 4)
        self.assertEqual(result["verdict"], "值得阅读")

    @patch("rss_analyzer.scoring.score_article")
    def test_analyze_article_failure(self, mock_score_article):
        """测试分析失败"""
        # Mock 抛出异常
        mock_score_article.side_effect = Exception("API Error")

        result = analyze_article_with_llm("标题", "摘要", "内容")

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["score"])
        self.assertEqual(result["error"]["code"], "analysis_failed")

    @patch("rss_analyzer.scoring.score_article")
    def test_analyze_article_preserves_structured_scoring_error(self, mock_score_article):
        mock_score_article.return_value = {
            "status": "error",
            "score": None,
            "overall_score": None,
            "verdict": "分析失败",
            "reason": "invalid JSON",
            "error": {"code": "analysis_failed", "message": "invalid JSON"},
        }

        result = analyze_article_with_llm("标题", "摘要", "内容")

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["score"])
        self.assertEqual(result["error"]["message"], "invalid JSON")

    def test_generate_overall_summary_no_high_score_articles(self):
        from rss_analyzer.llm_analyzer import generate_overall_summary

        articles = [
            {"title": "Low 1", "score": 2.5, "analysis": {"score": 2.5}},
            {"title": "Low 2", "score": 1.0, "analysis": {"score": 1.0}},
        ]
        result = generate_overall_summary(articles)
        self.assertEqual(result, "没有值得总结的高质量文章。")

    @patch("rss_analyzer.llm_analyzer.OpenAI")
    def test_generate_overall_summary_success_and_fallback_keys(self, mock_openai_cls):
        from unittest.mock import MagicMock
        from rss_analyzer.llm_analyzer import generate_overall_summary

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "## 测试总结报告\n推荐阅读。"
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_response.id = "mock-id"
        mock_response.model = "mock-model"
        mock_response.created = 123456
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        # Article without "analysis" dict, using top-level fallbacks
        articles = [
            {
                "title": "Good Article",
                "url": "https://example.com/good",
                "score": 4.5,
                "summary": "Great content",
            }
        ]
        result = generate_overall_summary(articles)
        self.assertEqual(result, "## 测试总结报告\n推荐阅读。")
        self.assertTrue(mock_client.chat.completions.create.called)

    @patch("rss_analyzer.llm_analyzer.OpenAI")
    def test_generate_overall_summary_extra_body_opt_in_and_no_stdout_leak(
        self, mock_openai_cls
    ):
        import io
        import os
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock
        from rss_analyzer.llm_analyzer import generate_overall_summary

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "## Report"
        mock_response = MagicMock(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        articles = [{"title": "Good", "score": 4.2, "summary": "Nice"}]

        buf = io.StringIO()
        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-supersecret12345678"}, clear=True
        ):
            with redirect_stdout(buf):
                result = generate_overall_summary(articles)

        self.assertEqual(result, "## Report")
        self.assertEqual(buf.getvalue(), "")
        self.assertNotIn("extra_body", mock_client.chat.completions.create.call_args.kwargs)

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-supersecret12345678",
                "SUMMARY_ENABLE_THINKING": "1",
            },
            clear=True,
        ):
            generate_overall_summary(articles)

        self.assertEqual(
            mock_client.chat.completions.create.call_args.kwargs.get("extra_body"),
            {"enable_thinking": True},
        )

    @patch("rss_analyzer.llm_analyzer.OpenAI")
    def test_generate_overall_summary_handles_none_score_and_bad_detailed_scores(
        self, mock_openai_cls
    ):
        from unittest.mock import MagicMock
        from rss_analyzer.llm_analyzer import generate_overall_summary

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "## Clean Report"
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )
        mock_openai_cls.return_value = mock_client

        articles = [
            {
                "title": "Failed article",
                "score": None,
                "detailed_scores": None,
                "analysis": {"score": None, "detailed_scores": "invalid"},
            },
            {
                "title": "Valid article",
                "score": 4.1,
                "detailed_scores": None,
                "summary": "Solid read",
            },
        ]
        result = generate_overall_summary(articles)
        self.assertEqual(result, "## Clean Report")

    @patch("rss_analyzer.llm_analyzer.OpenAI")
    def test_summarize_article_handles_empty_choices(self, mock_openai_cls):
        from unittest.mock import MagicMock
        from rss_analyzer.llm_analyzer import summarize_single_article

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(choices=[])
        mock_openai_cls.return_value = mock_client

        result = summarize_single_article("Some article content")
        self.assertIn("Summarization failed", result)

    @patch("rss_analyzer.llm_analyzer.OpenAI")
    def test_generate_overall_summary_handles_empty_choices(self, mock_openai_cls):
        from unittest.mock import MagicMock
        from rss_analyzer.llm_analyzer import generate_overall_summary

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(choices=[])
        mock_openai_cls.return_value = mock_client

        result = generate_overall_summary(
            [{"title": "Good", "score": 4.2, "summary": "Solid read"}]
        )
        self.assertIn("生成总结失败", result)


if __name__ == "__main__":
    unittest.main()
