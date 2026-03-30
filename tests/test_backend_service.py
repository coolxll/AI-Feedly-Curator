import unittest
from unittest.mock import Mock, patch

from rss_analyzer.backend_service import (
    _deep_analyze_digest_candidates,
    _deep_analysis_log_step,
    get_runtime_paths,
    handle_message,
    process_stream,
)


class TestBackendService(unittest.TestCase):
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

    @patch("rss_analyzer.backend_service.is_vector_store_enabled", return_value=False)
    def test_semantic_search_returns_disabled_state_when_vector_store_is_off(
        self, mock_vector_enabled
    ):
        response = handle_message({"type": "semantic_search", "query": "AI", "limit": 3})

        self.assertEqual(response["query"], "AI")
        self.assertEqual(response["results"], [])
        self.assertTrue(response["disabled"])
        mock_vector_enabled.assert_called()

    @patch("rss_analyzer.backend_service.is_vector_store_enabled", return_value=False)
    def test_rebuild_vector_store_returns_disabled_error_when_vector_store_is_off(
        self, mock_vector_enabled
    ):
        response = handle_message({"type": "rebuild_vector_store"})

        self.assertEqual(response["error"], "vector_store_disabled")
        mock_vector_enabled.assert_called()

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.analyze_articles_with_llm_batch")
    def test_get_scores_prefers_cached_results(self, mock_batch, mock_cached_score):
        mock_cached_score.return_value = {
            "score": 4.2,
            "data": {"title": "Cached title", "summary": "Cached summary"},
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

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.save_cached_score")
    @patch("rss_analyzer.backend_service.summarize_single_article")
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

    @patch("rss_analyzer.backend_service.get_cached_score")
    @patch("rss_analyzer.backend_service.save_cached_score")
    @patch("rss_analyzer.backend_service.summarize_single_article")
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

    @patch("rss_analyzer.backend_service.save_articles")
    @patch("rss_analyzer.backend_service.feedly_fetch_unread")
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

    @patch("rss_analyzer.backend_service.generate_summary_report")
    @patch("rss_analyzer.backend_service.load_articles")
    @patch("rss_analyzer.backend_service.os.path.exists")
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

    @patch("rss_analyzer.backend_service.analyze_articles")
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
            input_file="output\\unread_news.json",
            limit=10,
            mark_read=True,
            refresh=False,
            stream_id=None,
            threads=4,
        )

    @patch("rss_analyzer.backend_service.run_filter_workflow")
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

    @patch("rss_analyzer.backend_service.process_stream")
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

    @patch("rss_analyzer.backend_service.mark_stream_low_priority_read")
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

    @patch("rss_analyzer.backend_service.render_stream_overview_markdown")
    @patch("rss_analyzer.backend_service.analyze_article_with_llm")
    @patch("rss_analyzer.backend_service.fetch_filter_articles")
    @patch("rss_analyzer.backend_service.generate_stream_overview")
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

        result = process_stream(stream_id="feed/v2ex", stream_label="Feed: V2EX")

        self.assertEqual(result["digest"]["deep_analyzed_reads"], [])
        self.assertEqual(len(result["digest"]["clear_items"]), 1)
        self.assertEqual(result["mark_read_candidates"], ["1"])

    @patch("rss_analyzer.backend_service.logger")
    @patch("rss_analyzer.backend_service.analyze_article_with_llm")
    @patch("rss_analyzer.backend_service._prepare_article_analysis_inputs")
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

    @patch("rss_analyzer.backend_service.logger")
    @patch(
        "rss_analyzer.backend_service.analyze_article_with_llm",
        side_effect=Exception("boom"),
    )
    @patch(
        "rss_analyzer.backend_service._prepare_article_analysis_inputs",
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

    @patch("rss_analyzer.backend_service.feedly_mark_read")
    @patch("rss_analyzer.backend_service.get_cached_score")
    def test_low_score_filter_does_not_mark_read_inline(
        self, mock_get_cached_score, mock_feedly_mark_read
    ):
        from rss_analyzer.backend_service import low_score_filter

        mock_get_cached_score.return_value = {"score": 2.1}
        result = low_score_filter(
            [{"id": "article-1", "title": "Low score article"}],
            threshold=3.0,
            dry_run=False,
            mark_read=True,
        )

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.label, "low-score")
        mock_feedly_mark_read.assert_not_called()

    @patch("rss_analyzer.backend_service.run_filter_pipeline")
    @patch("rss_analyzer.backend_service.fetch_filter_articles")
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

    @patch("rss_analyzer.backend_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.backend_service.iter_cached_scores")
    @patch("rss_analyzer.backend_service.build_vector_store_payload")
    @patch("rss_analyzer.backend_service.get_vector_store")
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

    @patch("rss_analyzer.backend_service.is_vector_store_enabled", return_value=True)
    @patch.dict("os.environ", {"RSS_VECTOR_REBUILD_RESUME": "true"}, clear=False)
    @patch("rss_analyzer.backend_service.iter_cached_scores")
    @patch("rss_analyzer.backend_service.build_vector_store_payload")
    @patch("rss_analyzer.backend_service.get_vector_store")
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

    @patch("rss_analyzer.backend_service.is_vector_store_enabled", return_value=True)
    @patch("rss_analyzer.backend_service.get_vector_store")
    def test_rebuild_vector_store_returns_error_when_vector_store_unavailable(
        self, mock_get_vector_store, mock_vector_enabled
    ):
        vector_store = Mock()
        vector_store.collection = None
        mock_get_vector_store.return_value = vector_store

        response = handle_message({"type": "rebuild_vector_store"})

        self.assertEqual(response["error"], "vector_store_unavailable")


if __name__ == "__main__":
    unittest.main()
