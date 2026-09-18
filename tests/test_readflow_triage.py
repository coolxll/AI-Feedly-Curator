import unittest

from rss_analyzer.readflow_triage import (
    build_readflow_triage_prompt,
    coerce_readflow_decision,
    normalize_readflow_domain,
    parse_readflow_triage_results,
)


class TestReadflowTriage(unittest.TestCase):
    def test_prompt_includes_summary_content_and_quality_flags(self):
        prompt = build_readflow_triage_prompt(
            [
                {
                    "title": "例行声明",
                    "origin": "Reuters",
                    "summary": "<p>美国与欧盟讨论对俄罗斯的新制裁方案。</p>",
                    "content": "正文提供更多制裁细节。",
                    "content_source": "fetched",
                    "quality_flags": ["short_summary"],
                }
            ]
        )

        self.assertIn("不要只按标题吸引力评分", prompt)
        self.assertIn("美国与欧盟讨论对俄罗斯的新制裁方案", prompt)
        self.assertIn("正文提供更多制裁细节", prompt)
        self.assertIn("short_summary", prompt)

    def test_parse_results_normalizes_fields(self):
        result = parse_readflow_triage_results(
            [{"id": "1", "title": "声明", "summary": "摘要"}],
            [
                {
                    "n": 1,
                    "domain": "国际政治",
                    "score": 4.2,
                    "decision": "strong_recommend",
                    "event": "新制裁方案",
                    "core_fact": "讨论新制裁",
                    "needs_deep_read": "true",
                }
            ],
        )

        self.assertEqual(result["1"]["domain"], "P2")
        self.assertEqual(result["1"]["decision"], "must_read")
        self.assertTrue(result["1"]["needs_deep_read"])
        self.assertEqual(result["1"]["similarity_key"], "新制裁方案")

    def test_domain_and_decision_fallbacks(self):
        self.assertEqual(normalize_readflow_domain("AI"), "Tech")
        self.assertEqual(normalize_readflow_domain("unknown"), "Other")
        self.assertEqual(coerce_readflow_decision(None, 4.0), "must_read")
        self.assertEqual(coerce_readflow_decision(None, 3.0), "skim")
        self.assertEqual(coerce_readflow_decision(None, 1.0), "clear")


if __name__ == "__main__":
    unittest.main()
