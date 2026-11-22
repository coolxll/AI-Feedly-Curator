import unittest
from unittest.mock import Mock, patch

from rss_analyzer.backend_service import (
    BATCH_READ_FETCH_LIMIT,
    MESSAGE_HANDLERS,
    STREAM_HANDLERS,
    _build_batch_triage_prompt,
    _deep_analyze_digest_candidates,
    _deep_analysis_log_step,
    _parse_batch_triage_results,
    get_runtime_paths,
    handle_message,
    process_batch,
    process_stream,
)
from rss_analyzer.config import PROJ_CONFIG


class TestBackendService(unittest.TestCase):
    def test_facade_keeps_public_workflow_exports(self):
        from rss_analyzer import backend_service

        expected_exports = {
            "analyze_articles",
            "export_articles",
            "generate_summary_report",
            "regenerate_summary",
            "process_stream",
            "process_batch",
            "run_filter_workflow",
            "mark_articles_read",
            "mark_stream_low_priority_read",
            "save_stream_overview_markdown",
        }

        self.assertTrue(
            all(callable(getattr(backend_service, name, None)) for name in expected_exports)
        )

    def test_message_handler_registry_contains_all_public_operations(self):
        self.assertEqual(
            set(MESSAGE_HANDLERS),
            {
                "get_vector_index_queue",
                "retry_vector_indexing",
                "get_score",
                "get_scores",
                "export_articles",
                "run_analysis",
                "generate_summary",
                "generate_daily_digest",
                "run_filters",
                "process_stream",
                "analyze_article",
                "summarize_article",
                "mark_stream_low_priority_read",
                "semantic_search",
                "get_article_tags",
                "discover_trending_topics",
                "delete_article",
                "clear_vector_store",
                "get_vector_store_stats",
                "rebuild_vector_store",
                "cleanup_invalid_entries",
                "health",
            },
        )

    def test_stream_handler_registry_is_an_explicit_message_subset(self):
        self.assertEqual(
            set(STREAM_HANDLERS),
            {
                "run_analysis",
                "generate_daily_digest",
                "process_stream",
                "rebuild_vector_store",
            },
        )
        self.assertLessEqual(set(STREAM_HANDLERS), set(MESSAGE_HANDLERS))

    def test_batch_triage_prompt_uses_feedly_summary(self):
        prompt = _build_batch_triage_prompt(
            [
                {
                    "id": "p2-1",
                    "title": "例行声明",
                    "origin": "Reuters",
                    "summary": "<p>美国与欧盟讨论对俄罗斯的新制裁方案。</p>",
                }
            ]
        )

        self.assertIn("例行声明", prompt)
        self.assertIn("美国与欧盟讨论对俄罗斯的新制裁方案", prompt)
        self.assertIn("不要只按标题吸引力评分", prompt)

    def test_parse_batch_triage_results_normalizes_p2_fields(self):
        articles = [{"id": "p2-1", "title": "例行声明", "summary": "摘要"}]
        result = _parse_batch_triage_results(
            articles,
            [
                {
                    "n": 1,
                    "domain": "国际政治",
                    "domain_confidence": 0.9,
                    "score": 4.1,
                    "decision": "must_read",
                    "event": "新制裁方案",
                    "actors": "美国,欧盟,俄罗斯",
                    "region": "欧洲",
                    "core_fact": "双方讨论新制裁",
                    "why_it_matters": "影响俄欧关系",
                    "novelty": "new",
                    "needs_deep_read": True,
                    "rec": "看新增细节",
                }
            ],
        )

        self.assertEqual(result["p2-1"]["domain"], "P2")
        self.assertEqual(result["p2-1"]["decision"], "must_read")
        self.assertTrue(result["p2-1"]["needs_deep_read"])

    @patch("rss_analyzer.readflow_workflows._deep_analyze_digest_candidates")
    @patch("rss_analyzer.readflow_workflows._batch_triage_articles")
    @patch("rss_analyzer.readflow_workflows.fetch_filter_articles")
    def test_process_batch_builds_p2_briefing_without_fetch_limit_from_chunk_size(
        self,
        mock_fetch_filter_articles,
        mock_batch_triage,
        mock_deep_analyze,
    ):
        mock_fetch_filter_articles.return_value = [
            {
                "id": "p2-1",
                "title": "例行声明",
                "link": "https://example.com/p2",
                "origin": "Reuters",
                "summary": "美国与欧盟讨论对俄罗斯的新制裁方案。" * 20,
                "published": 4102444800000,
            },
            {
                "id": "tech-1",
                "title": "Python 工具更新",
                "link": "https://example.com/tech",
                "origin": "Blog",
                "summary": "开发工具发布新版本，包含多项性能改进和新功能。" * 10,
                "published": 4102444800000,
            },
        ]
        mock_batch_triage.return_value = {
            "p2-1": {
                "domain": "P2",
                "domain_confidence": 0.95,
                "score": 4.2,
                "decision": "must_read",
                "event": "新制裁方案",
                "actors": "美国,欧盟,俄罗斯",
                "region": "欧洲",
                "core_fact": "讨论新制裁方案",
                "why_it_matters": "影响俄欧关系",
                "novelty": "new",
                "needs_deep_read": False,
                "rec": "看新增细节",
            },
            "tech-1": {
                "domain": "Tech",
                "domain_confidence": 0.9,
                "score": 2.3,
                "decision": "clear",
                "event": "工具更新",
                "actors": "",
                "region": "",
                "core_fact": "常规版本更新",
                "why_it_matters": "",
                "novelty": "repeat",
                "needs_deep_read": False,
                "rec": "可清理",
            },
        }
        def fill_triage_stats(_articles, _batch_size, stats=None):
            if stats is not None:
                stats.update(
                    {
                        "triage_cached_count": 0,
                        "triage_uncached_count": 2,
                        "llm_chunk_count": 2,
                        "fallback_chunk_count": 0,
                        "llm_chunk_size": 1,
                    }
                )
            return mock_batch_triage.return_value
        mock_batch_triage.side_effect = fill_triage_stats
        mock_deep_analyze.return_value = []

        result = process_batch(stream_id="feed/all", batch_size=1, days=3)

        mock_fetch_filter_articles.assert_called_once_with(
            BATCH_READ_FETCH_LIMIT,
            stream_id="feed/all",
        )
        mock_batch_triage.assert_called_once()
        self.assertEqual(mock_batch_triage.call_args.args[1], 1)
        self.assertEqual(result["digest"]["stats"]["p2_count"], 1)
        self.assertEqual(result["digest"]["stats"]["llm_chunk_count"], 2)
        self.assertEqual(result["digest"]["stats"]["triage_uncached_count"], 2)
        self.assertEqual(result["digest"]["p2_briefing"]["must_read"][0]["id"], "p2-1")
        self.assertEqual(result["mark_read_candidates"], ["tech-1"])

    def test_deep_analysis_log_step_scales_with_batch_size(self):
        self.assertEqual(_deep_analysis_log_step(3), 1)
        self.assertEqual(_deep_analysis_log_step(10), 2)
        self.assertEqual(_deep_analysis_log_step(20), 5)

    def test_health_message_exposes_runtime_paths(self):
        response = handle_message({"type": "health"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["service"], "rss-backend")
        runtime = get_runtime_paths()
        self.assertEqual(response["db_path"], runtime["db_path"])
        self.assertEqual(response["vector_enabled"], runtime["vector_enabled"])
        self.assertEqual(response["vector_db_dir"], runtime["vector_db_dir"])
        self.assertEqual(response["vector_backend"], runtime["vector_backend"])
        self.assertEqual(response["vector_http_url"], runtime["vector_http_url"])

    @patch("rss_analyzer.vector_handlers.is_vector_store_enabled", return_value=False)
    def test_semantic_search_returns_disabled_state_when_vector_store_is_off(
        self, mock_vector_enabled
    ):
        response = handle_message({"type": "semantic_search", "query": "AI", "limit": 3})

        self.assertEqual(response["query"], "AI")
        self.assertEqual(response["results"], [])
        self.assertTrue(response["disabled"])
        mock_vector_enabled.assert_called()

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=False)
    def test_rebuild_vector_store_returns_disabled_error_when_vector_store_is_off(
        self, mock_vector_enabled
    ):
        response = handle_message({"type": "rebuild_vector_store"})

        self.assertEqual(response["error"], "vector_store_disabled")
        mock_vector_enabled.assert_called()

    @patch("rss_analyzer.analysis_handlers.get_cached_score")
    @patch("rss_analyzer.analysis_handlers.analyze_articles_with_llm_batch")
    def test_get_scores_prefers_cached_results(self, mock_batch, mock_cached_score):
        mock_cached_score.return_value = {
            "score": 4.2,
            "data": {
                "status": "success",
                "score": 4.2,
                "title": "Cached title",
                "summary": "Cached summary",
            },
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "get_scores",
                "items": [{"id": "article-1", "title": "Ignored title"}],
            }
        )

        self.assertIn("article-1", response["items"])
        self.assertTrue(response["items"]["article-1"]["found"])
        self.assertEqual(response["items"]["article-1"]["score"], 4.2)
        mock_batch.assert_not_called()

    @patch("rss_analyzer.analysis_handlers.save_cached_score")
    @patch("rss_analyzer.analysis_handlers.analyze_articles_with_llm_batch")
    @patch("rss_analyzer.analysis_handlers.get_cached_score", return_value=None)
    def test_get_scores_does_not_cache_failed_analysis(
        self, mock_cached_score, mock_batch, mock_save
    ):
        failed_result = {
            "status": "error",
            "score": None,
            "reason": "provider timeout",
            "error": {"code": "analysis_failed", "message": "provider timeout"},
        }
        mock_batch.return_value = [
            {
                **failed_result,
            }
            for _ in range(11)
        ]

        response = handle_message(
            {
                "type": "get_scores",
                "items": [
                    {"id": f"article-{index}", "title": f"Title {index}"}
                    for index in range(1, 12)
                ],
            }
        )

        self.assertEqual(response["items"]["article-1"]["status"], "error")
        self.assertIsNone(response["items"]["article-1"]["score"])
        self.assertFalse(response["items"]["article-1"]["found"])
        mock_save.assert_not_called()

    @patch("rss_analyzer.analysis_handlers.get_cached_score")
    @patch("rss_analyzer.analysis_handlers.save_cached_score")
    @patch("rss_analyzer.analysis_handlers.summarize_single_article")
    def test_summarize_article_updates_cache(self, mock_summarize, mock_save, mock_cached):
        mock_summarize.return_value = "summary body"
        mock_cached.return_value = {
            "score": 3.9,
            "data": {"title": "Existing title"},
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "summarize_article",
                "id": "article-2",
                "title": "New title",
                "url": "https://example.com/article",
                "content": "Long enough content" * 20,
            }
        )

        self.assertEqual(response["summary"], "summary body")
        mock_summarize.assert_called_once_with("Long enough content" * 20, task="summary")
        mock_save.assert_called_once()
        _, _, saved_data = mock_save.call_args.args
        self.assertEqual(saved_data["summary"], "summary body")
        self.assertEqual(saved_data["url"], "https://example.com/article")

    @patch("rss_analyzer.analysis_handlers.get_cached_score")
    @patch("rss_analyzer.analysis_handlers.save_cached_score")
    @patch("rss_analyzer.analysis_handlers.summarize_single_article")
    def test_summarize_article_returns_error_without_caching_on_failure(
        self, mock_summarize, mock_save, mock_cached
    ):
        mock_summarize.return_value = "Summarization failed: invalid model"
        mock_cached.return_value = {
            "score": 3.9,
            "data": {"title": "Existing title"},
            "updated_at": "2026-03-26T10:00:00",
        }

        response = handle_message(
            {
                "type": "summarize_article",
                "id": "article-3",
                "title": "Title",
                "content": "Long enough content" * 20,
            }
        )

        self.assertEqual(response["error"], "summary_failed")
        self.assertIn("invalid model", response["message"])
        mock_save.assert_not_called()

    def test_unknown_message_type(self):
        response = handle_message({"type": "does_not_exist"})
        self.assertEqual(response, {"error": "unknown_type"})

    def test_unhashable_message_type_remains_an_unknown_type(self):
        response = handle_message({"type": ["not", "valid"]})
        self.assertEqual(response, {"error": "unknown_type"})

    @patch("rss_analyzer.report_service.save_articles")
    @patch("rss_analyzer.report_service.feedly_fetch_unread")
    def test_export_articles_handler_saves_fetched_articles(
        self, mock_feedly_fetch_unread, mock_save_articles
    ):
        mock_feedly_fetch_unread.return_value = [
            {"id": "article-1", "title": "Title 1"},
            {"id": "article-2", "title": "Title 2"},
        ]

        output_file = "output/export.json"
        response = handle_message(
            {
                "type": "export_articles",
                "limit": 2,
                "stream_id": "feed/123",
                "output_file": output_file,
            }
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["article_count"], 2)
        mock_feedly_fetch_unread.assert_called_once_with(
            limit=2, stream_id="feed/123"
        )
        mock_save_articles.assert_called_once()

    @patch("rss_analyzer.report_service.generate_summary_report")
    @patch("rss_analyzer.report_service.load_articles")
    @patch("rss_analyzer.report_service.os.path.exists")
    def test_generate_summary_handler_uses_input_file_when_articles_omitted(
        self, mock_exists, mock_load_articles, mock_generate_summary_report
    ):
        mock_exists.return_value = True
        mock_load_articles.return_value = []
        mock_generate_summary_report.return_value = {
            "success": True,
            "summary": "summary",
            "summary_file": "output/2026-03/summary_1.md",
            "latest_summary_file": "output/summary_latest.md",
        }

        input_file = "output/analyzed_articles_latest.json"
        response = handle_message({"type": "generate_summary", "input_file": input_file})

        self.assertTrue(response["success"])
        self.assertEqual(response["input_file"], input_file)
        mock_generate_summary_report.assert_called_once_with([])

    @patch("rss_analyzer.feedly_handlers.analyze_articles")
    def test_run_analysis_handler_coerces_string_booleans(
        self, mock_analyze_articles
    ):
        mock_analyze_articles.return_value = {"success": True}

        response = handle_message(
            {
                "type": "run_analysis",
                "limit": 10,
                "refresh": "false",
                "mark_read": "true",
                "threads": 4,
            }
        )

        self.assertTrue(response["success"])
        mock_analyze_articles.assert_called_once_with(
            input_file=PROJ_CONFIG["input_file"],
            limit=10,
            mark_read=True,
            refresh=False,
            stream_id=None,
            threads=4,
        )

    @patch("rss_analyzer.feed_analysis_workflow.generate_summary_report", return_value={})
    @patch("rss_analyzer.feed_analysis_workflow.feedly_mark_read", return_value=True)
    @patch("rss_analyzer.feed_analysis_workflow.save_cached_score")
    @patch("rss_analyzer.feed_analysis_workflow.get_cached_score", return_value=None)
    @patch("rss_analyzer.feed_analysis_workflow.analyze_article_with_llm")
    @patch("rss_analyzer.feed_analysis_workflow.save_articles")
    @patch("rss_analyzer.feed_analysis_workflow.load_articles")
    @patch("rss_analyzer.feed_analysis_workflow.os.path.exists", return_value=True)
    def test_analyze_articles_marks_only_successful_results_read(
        self,
        mock_exists,
        mock_load_articles,
        mock_save_articles,
        mock_analyze,
        mock_get_cached_score,
        mock_save_cached_score,
        mock_mark_read,
        mock_summary,
    ):
        from rss_analyzer.backend_service import analyze_articles

        mock_load_articles.return_value = [
            {"id": "ok", "title": "Successful", "content": "x" * 300},
            {"id": "failed", "title": "Failed", "content": "x" * 300},
        ]
        mock_analyze.side_effect = [
            {
                "status": "success",
                "score": 4.0,
                "verdict": "值得阅读",
                "reason": "useful",
            },
            {
                "status": "error",
                "score": None,
                "reason": "timeout",
                "error": {"code": "analysis_failed", "message": "timeout"},
            },
        ]

        events = []
        with patch.dict(PROJ_CONFIG, {"batch_scoring": False}):
            result = analyze_articles(
                refresh=False,
                mark_read=True,
                limit=2,
                progress_callback=events.append,
            )

        mock_mark_read.assert_called_once_with(["ok"])
        self.assertEqual(result["successful_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["marked_read_count"], 1)
        self.assertIn("article_completed", [event["event"] for event in events])
        self.assertIn("article_failed", [event["event"] for event in events])
        self.assertEqual(events[-1]["phase"], "completed")

    @patch("rss_analyzer.feedly_handlers.analyze_articles")
    def test_stream_dispatcher_passes_progress_callback(self, mock_analyze_articles):
        from rss_analyzer.backend_service import handle_stream_message

        mock_analyze_articles.return_value = {"success": True}
        events = []
        callback = events.append

        response = handle_stream_message(
            {"type": "run_analysis", "limit": 5, "refresh": False},
            callback,
        )

        self.assertTrue(response["success"])
        self.assertIs(mock_analyze_articles.call_args.kwargs["progress_callback"], callback)

    @patch("rss_analyzer.feedly_handlers.run_filter_workflow")
    def test_run_filters_handler_coerces_values(self, mock_run_filter_workflow):
        mock_run_filter_workflow.return_value = {"success": True}

        response = handle_message(
            {
                "type": "run_filters",
                "mode": "low-score",
                "limit": "25",
                "threshold": "2.5",
                "dry_run": "true",
                "mark_read": "false",
                "stream_id": "feed/abc",
            }
        )

        self.assertTrue(response["success"])
        mock_run_filter_workflow.assert_called_once_with(
            mode="low-score",
            limit=25,
            threshold=2.5,
            dry_run=True,
            mark_read=False,
            stream_id="feed/abc",
        )

    @patch("rss_analyzer.feedly_handlers.process_stream")
    def test_process_stream_handler_coerces_values(self, mock_process_stream):
        mock_process_stream.return_value = {"success": True, "strategy": "radar"}

        response = handle_message(
            {
                "type": "process_stream",
                "stream_id": "feed/v2ex",
                "stream_label": "Feed: V2EX",
                "days": "3",
                "limit": "200",
                "export_markdown": "true",
            }
        )

        self.assertTrue(response["success"])
        mock_process_stream.assert_called_once_with(
            stream_id="feed/v2ex",
            stream_label="Feed: V2EX",
            days=3,
            limit=200,
            strategy=None,
            export_markdown=True,
        )

    @patch("rss_analyzer.feedly_handlers.mark_stream_low_priority_read")
    def test_mark_stream_low_priority_read_handler_coerces_values(self, mock_mark_low):
        mock_mark_low.return_value = {"success": True, "marked_count": 2}

        response = handle_message(
            {
                "type": "mark_stream_low_priority_read",
                "article_ids": ["a", "b"],
                "dry_run": "false",
            }
        )

        self.assertTrue(response["success"])
        mock_mark_low.assert_called_once_with(["a", "b"], dry_run=False)

    @patch("rss_analyzer.readflow_workflows.render_stream_overview_markdown")
    @patch("rss_analyzer.readflow_workflows.analyze_article_with_llm")
    @patch("rss_analyzer.readflow_workflows.fetch_filter_articles")
    @patch("rss_analyzer.readflow_workflows.generate_stream_overview")
    def test_process_stream_demotes_low_score_must_read_after_analysis(
        self,
        mock_generate_stream_overview,
        mock_fetch_filter_articles,
        mock_analyze_article_with_llm,
        mock_render_markdown,
    ):
        mock_fetch_filter_articles.return_value = [
            {"id": "1", "title": "[问与答] 家庭求助", "link": "https://www.v2ex.com/t/1"}
        ]
        mock_generate_stream_overview.return_value = {
            "strategy": "radar",
            "article_count": 1,
            "summary": "old summary",
            "theme_groups": [],
            "worth_expanding_items": [],
            "worth_expanding_overflow_count": 0,
            "low_priority_items": [],
            "mark_read_candidates": [],
            "markdown": "old markdown",
            "digest": {
                "headline": "headline",
                "executive_summary": "summary",
                "must_read_candidates": [
                    {
                        "id": "1",
                        "title": "[问与答] 家庭求助",
                        "link": "https://www.v2ex.com/t/1",
                        "summary": "求助帖",
                    }
                ],
                "deep_analyzed_reads": [],
                "skim_items": [],
                "clear_items": [],
                "actions": [],
                "stats": {"fetched_count": 1, "candidate_count": 1},
            },
        }
        mock_analyze_article_with_llm.return_value = {
            "score": 1.0,
            "verdict": "不太值得阅读",
            "summary": "与关注主题无关",
            "reason": "irrelevant",
            "detailed_scores": {"relevance": 1},
        }
        mock_render_markdown.return_value = "digest markdown"

        with (
            patch("rss_analyzer.readflow_workflows.get_cached_score", return_value=None),
            patch("rss_analyzer.readflow_workflows.save_cached_score"),
        ):
            result = process_stream(stream_id="feed/v2ex", stream_label="Feed: V2EX")

        self.assertEqual(result["digest"]["deep_analyzed_reads"], [])
        self.assertEqual(len(result["digest"]["clear_items"]), 1)
        self.assertEqual(result["mark_read_candidates"], ["1"])

    @patch("rss_analyzer.readflow_workflows.logger")
    @patch("rss_analyzer.readflow_workflows.analyze_article_with_llm")
    @patch("rss_analyzer.readflow_workflows._prepare_article_analysis_inputs")
    def test_deep_analyze_digest_candidates_logs_progress_and_preserves_order(
        self,
        mock_prepare_inputs,
        mock_analyze_article_with_llm,
        mock_logger,
    ):
        items = [
            {"id": "1", "title": "First article", "link": "https://example.com/1"},
            {"id": "2", "title": "Second article", "link": "https://example.com/2"},
        ]
        mock_prepare_inputs.return_value = ("summary", "Long enough content" * 20)
        mock_analyze_article_with_llm.side_effect = [
            {"score": 4.2, "verdict": "值得阅读", "summary": "first", "reason": "r1"},
            {"score": 3.9, "verdict": "可选", "summary": "second", "reason": "r2"},
        ]

        with (
            patch("rss_analyzer.readflow_workflows.get_cached_score", return_value=None),
            patch("rss_analyzer.readflow_workflows.save_cached_score"),
        ):
            result = _deep_analyze_digest_candidates(items)

        self.assertEqual([item["id"] for item in result], ["1", "2"])
        self.assertEqual(result[0]["score"], 4.2)
        self.assertEqual(result[1]["score"], 3.9)
        info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
        self.assertIn(
            "Process Stream: deep analyzing %s must-read candidates with %s workers...",
            info_messages,
        )
        self.assertIn(
            "Process Stream: [%s/%s] deep analyzed %s (score: %.1f)",
            info_messages,
        )
        self.assertIn(
            "Process Stream: finished deep analysis for %s candidates (%s analyzed, %s skipped, %s failed).",
            info_messages,
        )

    @patch("rss_analyzer.readflow_workflows.logger")
    @patch(
        "rss_analyzer.readflow_workflows.analyze_article_with_llm",
        side_effect=Exception("boom"),
    )
    @patch(
        "rss_analyzer.readflow_workflows._prepare_article_analysis_inputs",
        return_value=("summary", "Long enough content" * 20),
    )
    def test_deep_analyze_digest_candidates_keeps_batch_running_on_single_failure(
        self,
        mock_prepare_inputs,
        mock_analyze_article_with_llm,
        mock_logger,
    ):
        items = [{"id": "1", "title": "Broken article", "link": "https://example.com/1"}]

        result = _deep_analyze_digest_candidates(items)

        self.assertEqual(result[0]["id"], "1")
        self.assertNotIn("score", result[0])
        mock_logger.warning.assert_called()

    @patch("rss_analyzer.filter_workflows.feedly_mark_read")
    @patch("rss_analyzer.filter_workflows.get_cached_score")
    def test_low_score_filter_does_not_mark_read_inline(
        self, mock_get_cached_score, mock_feedly_mark_read
    ):
        from rss_analyzer.backend_service import low_score_filter

        mock_get_cached_score.return_value = {
            "score": 2.1,
            "data": {"status": "success", "score": 2.1},
        }
        result = low_score_filter(
            [{"id": "article-1", "title": "Low score article"}],
            threshold=3.0,
            dry_run=False,
            mark_read=True,
        )

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.label, "low-score")
        mock_feedly_mark_read.assert_not_called()

    @patch("rss_analyzer.filter_workflows.feedly_mark_read")
    @patch("rss_analyzer.filter_workflows.get_cached_score", return_value=None)
    @patch("rss_analyzer.filter_workflows._score_article")
    def test_low_score_filter_keeps_failed_analysis(
        self, mock_score_article, mock_get_cached_score, mock_feedly_mark_read
    ):
        from rss_analyzer.backend_service import low_score_filter

        mock_score_article.return_value = (
            None,
            {
                "status": "error",
                "score": None,
                "error": {"code": "analysis_failed", "message": "timeout"},
            },
        )

        with patch.dict(PROJ_CONFIG, {"batch_scoring": False}):
            result = low_score_filter(
                [{"id": "article-1", "title": "Unavailable article"}],
                threshold=3.0,
                dry_run=False,
                mark_read=True,
                incremental_mark=True,
            )

        self.assertEqual(result.matched, [])
        self.assertEqual([item["id"] for item in result.remaining], ["article-1"])
        mock_feedly_mark_read.assert_not_called()

    @patch("rss_analyzer.filter_workflows.feedly_mark_read", return_value=True)
    @patch("rss_analyzer.filter_workflows.get_cached_score")
    def test_low_score_filter_incremental_mark_batches(
        self, mock_get_cached_score, mock_feedly_mark_read
    ):
        from rss_analyzer.backend_service import low_score_filter

        mock_get_cached_score.side_effect = [
            {"score": score, "data": {"status": "success", "score": score}}
            for score in (1.5, 2.0, 1.8, 2.2, 1.0)
        ]
        articles = [{"id": f"article-{i}", "title": f"Article {i}"} for i in range(1, 6)]

        result = low_score_filter(
            articles,
            threshold=3.0,
            dry_run=False,
            mark_read=True,
            incremental_mark=True,
            mark_batch_size=2,
        )

        self.assertEqual(len(result.matched), 5)
        self.assertEqual(len(result.remaining), 0)
        self.assertEqual(result.marked_ids, {f"article-{i}" for i in range(1, 6)})
        self.assertEqual(mock_feedly_mark_read.call_count, 3)
        mock_feedly_mark_read.assert_any_call(["article-1", "article-2"])
        mock_feedly_mark_read.assert_any_call(["article-3", "article-4"])
        mock_feedly_mark_read.assert_any_call(["article-5"])

    @patch("rss_analyzer.filter_workflows.feedly_mark_read")
    @patch("rss_analyzer.filter_workflows.get_cached_score")
    def test_low_score_filter_incremental_mark_dry_run(
        self, mock_get_cached_score, mock_feedly_mark_read
    ):
        from rss_analyzer.backend_service import low_score_filter

        mock_get_cached_score.return_value = {
            "score": 2.0,
            "data": {"status": "success", "score": 2.0},
        }
        articles = [{"id": "article-1", "title": "Article 1"}]

        result = low_score_filter(
            articles,
            threshold=3.0,
            dry_run=True,
            mark_read=True,
            incremental_mark=True,
            mark_batch_size=1,
        )

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(len(result.marked_ids), 0)
        mock_feedly_mark_read.assert_not_called()

    @patch("rss_analyzer.filter_workflows.feedly_mark_read")
    def test_run_filter_pipeline_skips_already_marked(self, mock_feedly_mark_read):
        from rss_analyzer.backend_service import FilterResult, run_filter_pipeline

        articles = [
            {"id": "article-1", "title": "Article 1"},
            {"id": "article-2", "title": "Article 2"},
        ]
        dummy_filter = lambda items: FilterResult(
            matched=[{"id": "article-1"}],
            remaining=[{"id": "article-2"}],
            label="low-score",
            marked_ids={"article-1"},
        )

        result = run_filter_pipeline(articles, [dummy_filter], dry_run=False, mark_read=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(result["remaining_count"], 1)
        mock_feedly_mark_read.assert_not_called()

    @patch("rss_analyzer.filter_workflows.run_filter_pipeline")
    @patch("rss_analyzer.filter_workflows.fetch_filter_articles")
    def test_run_filter_workflow_defaults_newsflash_to_36kr(
        self, mock_fetch_filter_articles, mock_run_filter_pipeline
    ):
        from rss_analyzer.backend_service import FEED_ID_36KR, run_filter_workflow

        mock_fetch_filter_articles.return_value = [{"id": "article-1", "title": "News"}]
        mock_run_filter_pipeline.return_value = {
            "success": True,
            "article_count": 1,
            "filtered_count": 1,
            "remaining_count": 0,
            "steps": [],
        }

        response = run_filter_workflow(mode="newsflash", limit=10)

        self.assertTrue(response["success"])
        self.assertEqual(response["stream_id"], FEED_ID_36KR)
        mock_fetch_filter_articles.assert_called_once_with(10, stream_id=FEED_ID_36KR)

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.vector_service.iter_cached_scores")
    @patch("rss_analyzer.vector_service.build_vector_store_payload")
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_rebuilds_from_cached_articles(
        self,
        mock_get_vector_store,
        mock_build_payload,
        mock_iter_cached_scores,
        mock_vector_enabled,
    ):
        vector_store = Mock()
        vector_store.backend = "http"
        vector_store.collection = object()
        vector_store.clear_collection.return_value = True
        vector_store.get_all_article_ids.return_value = []
        vector_store.get_article_count.return_value = 1
        vector_store.add_articles.return_value = {"success_count": 1, "failed_ids": []}
        mock_get_vector_store.return_value = vector_store

        mock_iter_cached_scores.return_value = [
            {
                "article_id": "article-1",
                "score": 4.3,
                "data": {"title": "Title", "summary": "Summary"},
                "updated_at": "2026-03-26T12:00:00",
            }
        ]
        mock_build_payload.return_value = {
            "article_id": "article-1",
            "document_text": "Title: Title\nContent: Summary",
            "metadata": {"score": 4.3, "title": "Title"},
        }

        response = handle_message({"type": "rebuild_vector_store"})

        self.assertTrue(response["success"])
        self.assertEqual(response["rebuilt_count"], 1)
        vector_store.clear_collection.assert_called_once()
        vector_store.refresh_embedding_fingerprint.assert_called_once()
        vector_store.add_articles.assert_called_once()

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch.dict("os.environ", {"RSS_VECTOR_REBUILD_RESUME": "true"}, clear=False)
    @patch("rss_analyzer.vector_service.iter_cached_scores")
    @patch("rss_analyzer.vector_service.build_vector_store_payload")
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_skips_existing_ids_in_resume_mode(
        self,
        mock_get_vector_store,
        mock_build_payload,
        mock_iter_cached_scores,
        mock_vector_enabled,
    ):
        vector_store = Mock()
        vector_store.backend = "http"
        vector_store.collection = object()
        vector_store.get_all_article_ids.return_value = ["article-1"]
        vector_store.get_article_count.return_value = 1
        vector_store.add_articles.return_value = {"success_count": 1, "failed_ids": []}
        mock_get_vector_store.return_value = vector_store

        mock_iter_cached_scores.return_value = [
            {
                "article_id": "article-1",
                "score": 4.3,
                "data": {"title": "Title 1", "summary": "Summary 1"},
                "updated_at": "2026-03-26T12:00:00",
            },
            {
                "article_id": "article-2",
                "score": 4.1,
                "data": {"title": "Title 2", "summary": "Summary 2"},
                "updated_at": "2026-03-26T12:00:01",
            },
        ]
        mock_build_payload.side_effect = [
            {
                "article_id": "article-1",
                "document_text": "Title: Title 1\nContent: Summary 1",
                "metadata": {"score": 4.3, "title": "Title 1"},
            },
            {
                "article_id": "article-2",
                "document_text": "Title: Title 2\nContent: Summary 2",
                "metadata": {"score": 4.1, "title": "Title 2"},
            },
        ]

        response = handle_message({"type": "rebuild_vector_store"})

        self.assertTrue(response["success"])
        self.assertEqual(response["rebuilt_count"], 1)
        self.assertEqual(response["skipped_count"], 1)
        vector_store.clear_collection.assert_not_called()
        vector_store.add_articles.assert_called_once()

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_returns_error_when_vector_store_unavailable(
        self, mock_get_vector_store, mock_vector_enabled
    ):
        vector_store = Mock()
        vector_store.collection = None
        mock_get_vector_store.return_value = vector_store

        response = handle_message({"type": "rebuild_vector_store"})

        self.assertEqual(response["error"], "vector_store_unavailable")

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.vector_service.iter_cached_scores", return_value=[])
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_refuses_to_clear_when_cache_empty(
        self, mock_get_vector_store, mock_iter_cached_scores, mock_vector_enabled
    ):
        from rss_analyzer.vector_service import rebuild_vector_store

        vector_store = Mock()
        vector_store.collection = object()
        mock_get_vector_store.return_value = vector_store

        response = rebuild_vector_store()

        self.assertEqual(response["error"], "empty_cache")
        self.assertFalse(response["success"])
        self.assertEqual(response["cached_count"], 0)
        self.assertFalse(response["cleared"])
        vector_store.clear_collection.assert_not_called()

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.vector_service.iter_cached_scores", return_value=[])
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_allows_empty_when_explicitly_requested(
        self, mock_get_vector_store, mock_iter_cached_scores, mock_vector_enabled
    ):
        from rss_analyzer.vector_service import rebuild_vector_store

        vector_store = Mock()
        vector_store.backend = "embedded"
        vector_store.collection = object()
        vector_store.clear_collection.return_value = True
        vector_store.get_article_count.return_value = 0
        mock_get_vector_store.return_value = vector_store

        response = rebuild_vector_store(allow_empty=True)

        self.assertTrue(response["success"])
        self.assertEqual(response["cached_count"], 0)
        self.assertEqual(response["concurrency"], 1)
        vector_store.clear_collection.assert_called_once()
        vector_store.refresh_embedding_fingerprint.assert_called_once()

    def test_rebuild_vector_store_rejects_concurrent_rebuild(self):
        from rss_analyzer import vector_service

        self.assertTrue(vector_service._REBUILD_LOCK.acquire(blocking=False))
        try:
            response = vector_service.rebuild_vector_store()
        finally:
            vector_service._REBUILD_LOCK.release()

        self.assertFalse(response["success"])
        self.assertEqual(response["error"], "rebuild_in_progress")

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch.dict("os.environ", {"RSS_VECTOR_REBUILD_RESUME": "1"}, clear=False)
    @patch("rss_analyzer.vector_service.iter_cached_scores")
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_refuses_resume_on_fingerprint_mismatch(
        self, mock_get_vector_store, mock_iter_cached_scores, mock_vector_enabled
    ):
        from rss_analyzer.vector_service import rebuild_vector_store

        vector_store = Mock()
        vector_store.backend = "embedded"
        vector_store.collection = object()
        vector_store.is_embedding_fingerprint_mismatch.return_value = True
        mock_get_vector_store.return_value = vector_store
        mock_iter_cached_scores.return_value = [
            {
                "article_id": "article-1",
                "score": 4.0,
                "data": {"title": "T", "summary": "S"},
                "updated_at": "2026-03-26T12:00:00",
            }
        ]

        response = rebuild_vector_store()

        self.assertFalse(response["success"])
        self.assertEqual(response["error"], "embedding_fingerprint_mismatch")
        vector_store.clear_collection.assert_not_called()
        vector_store.add_articles.assert_not_called()

    @patch("rss_analyzer.vector_service.is_vector_store_enabled", return_value=True)
    @patch.dict("os.environ", {"RSS_VECTOR_REBUILD_BATCH_SIZE": "1"}, clear=False)
    @patch("rss_analyzer.vector_service.iter_cached_scores")
    @patch("rss_analyzer.vector_service.build_vector_store_payload")
    @patch("rss_analyzer.vector_service.get_vector_store")
    def test_rebuild_vector_store_cancels_futures_when_progress_callback_raises(
        self,
        mock_get_vector_store,
        mock_build_payload,
        mock_iter_cached_scores,
        mock_vector_enabled,
    ):
        from rss_analyzer import vector_service

        vector_store = Mock()
        vector_store.backend = "embedded"
        vector_store.collection = object()
        vector_store.clear_collection.return_value = True
        vector_store.add_articles.return_value = {"success_count": 1, "failed_ids": []}
        mock_get_vector_store.return_value = vector_store
        mock_iter_cached_scores.return_value = [
            {"article_id": "a1", "score": 4.0, "data": {"title": "T1"}, "updated_at": "2026-03-26T12:00:00"},
            {"article_id": "a2", "score": 4.0, "data": {"title": "T2"}, "updated_at": "2026-03-26T12:00:01"},
        ]
        mock_build_payload.side_effect = [
            {"article_id": "a1", "document_text": "T1", "metadata": {"score": 4.0}},
            {"article_id": "a2", "document_text": "T2", "metadata": {"score": 4.0}},
        ]

        def failing_callback(event):
            if event.get("phase") == "indexing":
                raise BrokenPipeError("client disconnected")

        fake_executor = Mock()
        future1 = Mock()
        future1.result.return_value = {"success_count": 1, "failed_ids": []}
        future2 = Mock()
        fake_executor.submit.side_effect = [future1, future2]

        with (
            patch(
                "rss_analyzer.vector_service.concurrent.futures.ThreadPoolExecutor",
                return_value=fake_executor,
            ),
            patch(
                "rss_analyzer.vector_service.concurrent.futures.as_completed",
                return_value=[future1, future2],
            ),
        ):
            with self.assertRaises(BrokenPipeError):
                vector_service.rebuild_vector_store(progress_callback=failing_callback)

        fake_executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        # Lock must be released after failure
        self.assertTrue(vector_service._REBUILD_LOCK.acquire(blocking=False))
        vector_service._REBUILD_LOCK.release()

    def test_utils_is_newsflash_handles_none_link_and_save_articles_is_atomic(self):
        import json
        import tempfile
        from pathlib import Path
        from rss_analyzer.utils import is_newsflash, save_articles

        self.assertFalse(is_newsflash({"link": None}))
        self.assertTrue(
            is_newsflash({"link": "https://36kr.com/newsflashes/123456"})
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "nested" / "articles.json"
            save_articles([{"id": "1", "title": "Hello"}], str(target))
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["id"], "1")
            # No leftover temp files in directory
            self.assertEqual([p.name for p in target.parent.iterdir()], ["articles.json"])

    def test_report_service_build_monthly_path_and_atomic_summary_write(self):
        import tempfile
        from pathlib import Path
        from rss_analyzer import report_service

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            latest_path = Path(tmpdir) / "nested_latest" / "latest_summary.md"
            try:
                import os

                os.chdir(tmpdir)
                p1 = report_service.build_monthly_output_path("summary", "md")
                # Filename includes 6-digit microseconds
                self.assertRegex(Path(p1).name, r"^summary_\d{8}_\d{6}_\d{6}\.md$")

                with (
                    patch.object(
                        report_service,
                        "generate_overall_summary",
                        return_value="# Atomic Summary",
                    ),
                    patch.object(
                        report_service, "LATEST_SUMMARY_FILE", str(latest_path)
                    ),
                ):
                    result = report_service.generate_summary_report([{"title": "A"}])

                self.assertTrue(result["success"])
                self.assertEqual(
                    Path(result["summary_file"]).read_text(encoding="utf-8"),
                    "# Atomic Summary",
                )
                self.assertEqual(
                    latest_path.read_text(encoding="utf-8"),
                    "# Atomic Summary",
                )
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
