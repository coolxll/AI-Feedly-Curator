"""
测试评分模块
"""

import unittest
from unittest.mock import patch, Mock

from rss_analyzer.scoring import (
    build_scoring_prompt,
    calculate_weighted_score,
    calibrate_score_distribution,
    extract_json_from_response,
    parse_batch_score_response,
    parse_score_response,
    score_article,
)


class TestScoring(unittest.TestCase):
    """评分模块测试"""

    def test_build_scoring_prompt(self):
        """测试评分提示词构建"""
        prompt = build_scoring_prompt("测试标题", "测试摘要", "测试内容")

        self.assertIn("判断文章类型", prompt)
        self.assertIn("负面特征", prompt)
        self.assertIn("why_not_higher", prompt)
        self.assertIn("negative_signals", prompt)
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
            "why_not_higher": "虽然信息完整，但软文属性明显",
            "negative_signals": ["marketing_tone"],
            "comment": "虽然分高但是软文"
        }"""

        result = parse_score_response(response)

        self.assertLess(result["overall_score"], 4.5)
        self.assertEqual(result["why_not_higher"], "虽然信息完整，但软文属性明显")
        self.assertIn("marketing_tone", result["negative_signals"])
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
            "why_not_higher": "教程解决了问题，但方法不算新",
            "negative_signals": ["no_actionable_detail"],
            "comment": "文章质量不错"
        }"""

        result = parse_score_response(response)

        self.assertEqual(result["relevance_score"], 4)
        self.assertTrue(result["overall_score"] > 0)
        self.assertIn(result["verdict"], {"值得阅读", "一般，可选阅读"})
        self.assertEqual(result["article_type"], "tutorial")
        self.assertIn("why_not_higher", result)

    def test_parse_score_response_invalid(self):
        """测试解析无效响应"""
        result = parse_score_response("这不是JSON")

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["overall_score"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["verdict"], "分析失败")

    def test_calibrate_score_distribution_compresses_inflated_high_scores(self):
        calibrated = calibrate_score_distribution(
            5.0,
            {
                "relevance": 4,
                "informativeness_accuracy": 4,
                "depth_opinion": 4,
                "readability": 5,
                "non_redundancy": 3,
            },
            "opinion",
            [],
            ["low_novelty"],
            "观点完整，但没有太多新增信息",
        )

        self.assertLessEqual(calibrated, 3.7)

    @patch("rss_analyzer.scoring.OpenAI")
    @patch(
        "rss_analyzer.scoring.PROJ_CONFIG",
        {"scoring_persona": "", "scoring_weights": {}},
    )
    def test_score_article_success(self, mock_openai_class):
        """测试成功评分"""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = """{
            "analysis": "很有深度。",
            "why_not_higher": "仍然缺少真正稀缺的一手信息",
            "article_type": "opinion",
            "red_flags": [],
            "negative_signals": ["low_novelty"],
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

        self.assertIn(result["verdict"], {"值得阅读", "一般，可选阅读"})
        self.assertEqual(result["article_type"], "opinion")
        self.assertIn("why_not_higher", result)

    def test_calculate_weighted_score_ignores_hallucinated_keys_and_coerces_values(self):
        base_scores = {
            "relevance": 4,
            "informativeness_accuracy": 4,
            "depth_opinion": 4,
            "readability": 4,
            "non_redundancy": 4,
        }
        expected = calculate_weighted_score(base_scores, "news", [])

        # Extra hallucinated keys from LLM must not inflate the weighted score
        inflated_scores = {
            **base_scores,
            "creativity": 5,
            "bonus_factor": 5,
        }
        self.assertEqual(
            calculate_weighted_score(inflated_scores, "news", []),
            expected,
        )

        # Invalid/non-numeric score values and string red_flags must not crash
        messy_scores = {
            "relevance": "4",
            "informativeness_accuracy": "N/A",
            "depth_opinion": None,
            "readability": True,
            "non_redundancy": 3,
        }
        score_with_str_flag = calculate_weighted_score(
            messy_scores, "news", "clickbait"  # type: ignore[arg-type]
        )
        self.assertGreaterEqual(score_with_str_flag, 1.0)
        self.assertLessEqual(score_with_str_flag, 5.0)

    def test_calibrate_score_distribution_hard_red_flag_short_circuits(self):
        calibrated = calibrate_score_distribution(
            4.8,
            {
                "relevance": 5,
                "informativeness_accuracy": 5,
                "depth_opinion": 5,
                "readability": 5,
                "non_redundancy": 5,
            },
            "opinion",
            ["ai_generated"],
            [],
            "",
        )
        self.assertEqual(calibrated, 1.0)

    def test_calibrate_score_distribution_preserves_relevance_circuit_breaker(self):
        calibrated = calibrate_score_distribution(
            2.5,
            {
                "relevance": 1,
                "informativeness_accuracy": 5,
                "depth_opinion": 5,
                "readability": 5,
                "non_redundancy": 5,
            },
            "news",
            [],
            [],
            "",
        )
        self.assertLessEqual(calibrated, 2.5)

    def test_extract_json_from_response_validates_code_block_and_handles_braces_in_strings(
        self,
    ):
        # Invalid JSON inside code block should fall through to valid JSON in body,
        # even with a stray leading '}' and braces inside JSON string values.
        response = (
            "Here is a broken block:\n"
            "```json\n{not valid json}\n```\n"
            "Stray brace } before actual output:\n"
            '{"analysis": "Contains {braces} and \\"quotes\\" inside }", '
            '"scores": {"relevance": 4}}'
        )
        extracted = extract_json_from_response(response)
        self.assertIsNotNone(extracted)
        import json

        parsed = json.loads(extracted)
        self.assertEqual(parsed["scores"]["relevance"], 4)
        self.assertIn("{braces}", parsed["analysis"])

    def test_parse_batch_score_response_handles_string_index_and_malformed_item(self):
        response = """[
            {
                "index": "0",
                "analysis": "Valid item",
                "article_type": "news",
                "red_flags": [],
                "negative_signals": [],
                "scores": {
                    "relevance": 4,
                    "informativeness_accuracy": 4,
                    "depth_opinion": 3,
                    "readability": 4,
                    "non_redundancy": 4
                }
            },
            {
                "index": 1,
                "analysis": "Malformed scores field",
                "scores": "not-a-dict"
            }
        ]"""
        results = parse_batch_score_response(response, expected_count=2)
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0]["status"], "success")
        self.assertIsNone(results[1])

    def test_extract_json_array_validates_code_block_and_stops_at_depth_zero(self):
        from rss_analyzer.scoring import extract_json_array_from_response

        response = (
            "Broken code block:\n"
            "```json\n[not valid json]\n```\n"
            "Stray bracket [bad] ] then valid array:\n"
            '[{"index": 0, "analysis": "ok"}]'
        )
        extracted = extract_json_array_from_response(response)
        self.assertEqual(extracted, '[{"index": 0, "analysis": "ok"}]')

    def test_robust_parse_objects_extracts_regardless_of_key_order(self):
        from rss_analyzer.scoring import _robust_parse_objects

        truncated = (
            '[{"analysis": "First", "scores": {"relevance": 4}, "index": 0}, '
            '{"comment": "Second", "index": 1, "scores": {"relevance": 5}}, '
            '{"analysis": "Truncated", "index": 2'
        )
        objs = _robust_parse_objects(truncated)
        self.assertEqual(len(objs), 2)
        self.assertEqual([obj["index"] for obj in objs], [0, 1])

    @patch("rss_analyzer.scoring.OpenAI")
    def test_score_article_handles_empty_choices(self, mock_openai_cls):
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = Mock(choices=[])
        mock_openai_cls.return_value = mock_client

        result = score_article("Title", "Summary", "Content")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["score"])

    @patch("rss_analyzer.scoring.OpenAI")
    def test_score_articles_batch_handles_empty_choices(self, mock_openai_cls):
        from rss_analyzer.scoring import score_articles_batch

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = Mock(choices=[])
        mock_openai_cls.return_value = mock_client

        result = score_articles_batch(
            [{"title": "T1", "summary": "S1", "content": "C1"}], max_retries=1
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
