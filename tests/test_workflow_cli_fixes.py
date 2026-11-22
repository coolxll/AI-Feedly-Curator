"""Unit tests for readflow_workflows, article_analyzer CLI, and feedly_token CLI fixes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

import article_analyzer
import feedly_token
from rss_analyzer.config import PROJ_CONFIG
from rss_analyzer.feedly_auth import FeedlyAuthError
from rss_analyzer.readflow_workflows import (
    _batch_triage_articles,
    _deep_analyze_digest_candidates,
    _rerank_digest_after_analysis,
    process_batch,
)
from rss_analyzer.stream_strategy import (
    generate_quick_clear_overview,
    generate_radar_overview,
)


class TestReadflowWorkflowFixes(unittest.TestCase):
    @patch("rss_analyzer.readflow_workflows.mark_articles_read")
    @patch("rss_analyzer.readflow_workflows._deep_analyze_digest_candidates", return_value=[])
    @patch("rss_analyzer.readflow_workflows._batch_triage_articles")
    @patch("rss_analyzer.readflow_workflows.fetch_filter_articles")
    def test_process_batch_auto_mark_respects_score_threshold(
        self,
        mock_fetch,
        mock_triage,
        _mock_deep,
        mock_mark_read,
    ):
        now_ms = 9_999_999_999_000
        long_summary = "Detailed article summary content " * 10
        mock_fetch.return_value = [
            {"id": "low-1", "title": "Very Low", "published": now_ms, "origin": "FeedA", "summary": long_summary},
            {"id": "edge-2", "title": "At Threshold", "published": now_ms, "origin": "FeedA", "summary": long_summary},
            {"id": "high-3", "title": "Above Threshold", "published": now_ms, "origin": "FeedA", "summary": long_summary},
            {"id": "none-4", "title": "Missing Score", "published": now_ms, "origin": "FeedA", "summary": long_summary},
        ]
        mock_triage.return_value = {
            "low-1": {"domain": "Other", "score": 1.4, "decision": "clear", "source": "llm"},
            "edge-2": {"domain": "Other", "score": 2.0, "decision": "clear", "source": "llm"},
            "high-3": {"domain": "Other", "score": 2.4, "decision": "clear", "source": "llm"},
            "none-4": {"domain": "Other", "score": None, "decision": "clear", "source": "fallback"},
        }
        mock_mark_read.return_value = {"success": True, "marked_count": 1, "candidate_count": 1}

        with patch.dict(PROJ_CONFIG, {"auto_mark_read_threshold": 2.0}):
            result = process_batch(stream_id="feed/all", batch_size=10, days=3)

        self.assertTrue(result["success"])
        mock_mark_read.assert_called_once_with(["low-1"], dry_run=False)
        self.assertEqual(
            set(result["mark_read_candidates"]),
            {"low-1", "edge-2", "high-3", "none-4"},
        )

    @patch("rss_analyzer.readflow_workflows._save_batch_triage")
    @patch("rss_analyzer.readflow_workflows._cached_batch_triage", return_value=None)
    @patch("openai.OpenAI")
    def test_batch_triage_does_not_cache_omitted_or_failed_fallbacks(
        self,
        mock_openai_cls,
        _mock_cached,
        mock_save,
    ):
        articles = [
            {"id": "a1", "title": "Parsed Article", "summary": "s1"},
            {"id": "a2", "title": "Omitted Article", "summary": "s2"},
        ]
        fake_resp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='[{"n": 1, "domain": "Tech", "score": 4.1, "decision": "must_read"}]'
                    )
                )
            ]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = fake_resp
        mock_openai_cls.return_value = client

        result = _batch_triage_articles(articles, chunk_size=10)

        self.assertEqual(result["a1"]["source"], "llm")
        self.assertEqual(result["a2"]["source"], "fallback")
        mock_save.assert_called_once()
        self.assertEqual(mock_save.call_args[0][0]["id"], "a1")

        # Now verify full chunk failure never calls _save_batch_triage
        mock_save.reset_mock()
        client.chat.completions.create.side_effect = RuntimeError("LLM timeout")
        failed_result = _batch_triage_articles(articles, chunk_size=10)

        self.assertEqual(failed_result["a1"]["source"], "fallback")
        self.assertEqual(failed_result["a2"]["source"], "fallback")
        mock_save.assert_not_called()

    def test_deep_analyze_logging_and_rerank_handle_none_fields(self):
        # _rerank_digest_after_analysis must not crash when analysis/detailed_scores/verdict are None
        digest = {
            "deep_analyzed_reads": [
                {
                    "id": "a1",
                    "title": "None analysis",
                    "score": 4.2,
                    "verdict": None,
                    "analysis": None,
                },
                {
                    "id": "a2",
                    "title": "None detailed_scores",
                    "score": 3.0,
                    "verdict": None,
                    "analysis": {"detailed_scores": None},
                },
                {
                    "id": "a3",
                    "title": "None score",
                    "score": None,
                    "verdict": None,
                    "analysis": None,
                },
            ],
            "skim_items": [],
            "clear_items": [],
            "stats": {"fetched_count": 3, "candidate_count": 3},
        }
        reranked = _rerank_digest_after_analysis(digest)
        # a1 (relevance=0 <= 1) and a2 (relevance=0 <= 1) demoted to clear; a3 (score=None) retained
        self.assertEqual([i["id"] for i in reranked["deep_analyzed_reads"]], ["a3"])
        self.assertEqual({i["id"] for i in reranked["clear_items"]}, {"a1", "a2"})

        # _deep_analyze_digest_candidates must not crash logging when score is None
        fake_service = MagicMock()
        fake_service.analyze_prepared.return_value = {
            "status": "success",
            "score": None,
            "verdict": "推荐",
            "reason": "ok",
            "detailed_scores": {},
        }
        candidates = [
            {
                "id": "c1",
                "title": "Candidate",
                "summary": "A" * 200,
                "link": "https://example.com/c1",
            }
        ]
        with patch("rss_analyzer.readflow_workflows._get_analysis_service", return_value=fake_service):
            analyzed = _deep_analyze_digest_candidates(candidates)
        self.assertEqual(len(analyzed), 1)
        self.assertIsNone(analyzed[0]["score"])


class TestStreamStrategyFixes(unittest.TestCase):
    @patch("rss_analyzer.stream_strategy._llm_interpret_candidates", return_value={})
    @patch("rss_analyzer.stream_strategy._llm_summarize_theme_groups", return_value={})
    def test_radar_overview_preserves_pre_prefilter_article_count_and_clear_ratio(
        self, _mock_sum, _mock_interp
    ):
        now_ms = 9_999_999_999_000
        # Case 1: mix of prefiltered-out (ad keyword) and normal articles
        mixed = [
            {"id": "ad-1", "title": "推广: Buy Now", "published": now_ms, "summary": "buy", "origin": "FeedA"},
            {"id": "ad-2", "title": "推广: Discount", "published": now_ms, "summary": "buy", "origin": "FeedA"},
            {
                "id": "good-1",
                "title": "Deep Systems Engineering Post",
                "published": now_ms,
                "summary": "Detailed engineering writeup " * 15,
                "origin": "FeedA",
            },
        ]
        with patch.dict(PROJ_CONFIG, {"filter_keywords": ["推广"], "filter_url_patterns": []}):
            res = generate_radar_overview(mixed, stream_label="Test", days=3)

        self.assertEqual(res["article_count"], 3)
        self.assertEqual(res["digest"]["stats"]["fetched_count"], 3)
        self.assertLessEqual(res["digest"]["stats"]["clear_ratio"], 1.0)
        self.assertAlmostEqual(res["digest"]["stats"]["clear_ratio"], 2 / 3, places=4)

        # Case 2: all articles prefiltered out -> clear_ratio is 1.0 (not 0.0)
        all_ads = mixed[:2]
        with patch.dict(PROJ_CONFIG, {"filter_keywords": ["推广"], "filter_url_patterns": []}):
            res_all = generate_radar_overview(all_ads, stream_label="Test", days=3)

        self.assertEqual(res_all["article_count"], 2)
        self.assertEqual(res_all["digest"]["stats"]["fetched_count"], 2)
        self.assertAlmostEqual(res_all["digest"]["stats"]["clear_ratio"], 1.0, places=4)

    @patch("rss_analyzer.stream_strategy._llm_interpret_candidates", return_value={})
    def test_quick_clear_overview_considers_all_remaining_before_truncating(self, _mock_interp):
        now_ms = 9_999_999_999_000
        # Create 12 non-newsflash articles where the 12th has the highest rank (long summary + title)
        articles = [
            {
                "id": f"art-{i}",
                "title": f"Short {i}",
                "published": now_ms - (12 - i) * 1000,
                "summary": "brief",
                "origin": "FeedA",
            }
            for i in range(11)
        ]
        articles.append(
            {
                "id": "art-best",
                "title": "Comprehensive Deep Dive Architecture Guide",
                "published": now_ms,
                "summary": "In-depth technical analysis " * 30,
                "origin": "FeedA",
            }
        )

        res = generate_quick_clear_overview(articles, stream_label="News", days=3)
        selected_ids = [item["id"] for item in res["worth_expanding_items"]]
        self.assertIn("art-best", selected_ids)
        self.assertEqual(
            res["worth_expanding_overflow_count"],
            len(articles) - len(res["worth_expanding_items"]),
        )


class TestArticleAnalyzerCli(unittest.TestCase):
    @patch("article_analyzer.setup_logging")
    @patch("article_analyzer.analyze_articles")
    def test_analyze_errors_return_nonzero(self, mock_analyze, _mock_logging):
        for payload in (
            {"error": "auth_failed", "message": "expired"},
            {"error": "fetch_failed", "message": "network"},
            {"error": "input_not_found", "message": "missing"},
            {"success": False, "message": "generic failure"},
        ):
            with self.subTest(payload=payload):
                mock_analyze.return_value = payload
                self.assertEqual(article_analyzer.main([]), 1)

    @patch("article_analyzer.setup_logging")
    @patch("article_analyzer.export_articles")
    def test_export_errors_return_nonzero_and_success_returns_zero(self, mock_export, _mock_logging):
        mock_export.return_value = {"error": "auth_failed", "message": "expired"}
        self.assertEqual(article_analyzer.main(["--export", "out.json"]), 1)

        mock_export.return_value = {
            "success": True,
            "article_count": 3,
            "output_file": "out.json",
        }
        self.assertEqual(article_analyzer.main(["--export", "out.json"]), 0)


class TestFeedlyTokenCli(unittest.TestCase):
    def test_help_flags_exit_zero_and_unknown_command_exits_nonzero(self):
        # -h and --help should return normally (exit 0) without probing network
        with patch("feedly_token.cmd_check", side_effect=AssertionError("must not run")):
            feedly_token.main(["-h"])
            feedly_token.main(["--help"])

        with self.assertRaises(SystemExit) as ctx:
            feedly_token.main(["unknown-cmd"])
        self.assertNotEqual(ctx.exception.code, 0)

    @patch("feedly_token.refresh_access_token", side_effect=FeedlyAuthError("invalid refresh"))
    @patch("feedly_token._probe_profile", return_value=(401, None))
    @patch(
        "feedly_token.load_config",
        return_value={"token": "expired-token", "refresh_token": "bad-refresh"},
    )
    def test_cmd_check_auto_refresh_auth_error_exits_1(self, _mock_cfg, _mock_probe, _mock_refresh):
        with self.assertRaises(SystemExit) as ctx:
            feedly_token.cmd_check(auto_refresh=True)
        self.assertEqual(ctx.exception.code, 1)

    @patch("feedly_token.refresh_access_token", side_effect=requests.ConnectionError("timeout"))
    @patch("feedly_token._probe_profile", return_value=(401, None))
    @patch(
        "feedly_token.load_config",
        return_value={"token": "expired-token", "refresh_token": "some-refresh"},
    )
    def test_cmd_check_auto_refresh_network_error_exits_2(
        self, _mock_cfg, _mock_probe, _mock_refresh
    ):
        with self.assertRaises(SystemExit) as ctx:
            feedly_token.cmd_check(auto_refresh=True)
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
