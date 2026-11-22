import unittest
from unittest.mock import Mock, patch

from rss_analyzer.feedly_handlers import (
    FEEDLY_MESSAGE_HANDLERS,
    FEEDLY_STREAM_HANDLERS,
    handle_run_analysis,
    handle_run_filters,
    handle_process_stream,
    stream_process_stream,
    stream_run_analysis,
)
from rss_analyzer.vector_handlers import (
    handle_discover_trending_topics,
    handle_retry_vector_indexing,
    handle_semantic_search,
)


class TestFeedlyHandlers(unittest.TestCase):
    def test_registries_expose_feedly_operations(self):
        self.assertEqual(
            set(FEEDLY_MESSAGE_HANDLERS),
            {
                "run_analysis",
                "run_filters",
                "process_stream",
                "mark_stream_low_priority_read",
            },
        )
        self.assertEqual(
            set(FEEDLY_STREAM_HANDLERS),
            {"run_analysis", "process_stream"},
        )

    @patch("rss_analyzer.feedly_handlers.run_filter_workflow")
    def test_filter_handler_coerces_transport_values(self, run_filter_workflow):
        run_filter_workflow.return_value = {"success": True}

        result = handle_run_filters(
            {
                "mode": "low-score",
                "limit": "25",
                "threshold": "2.5",
                "dry_run": "yes",
                "mark_read": "false",
                "incremental_mark": "on",
                "mark_batch_size": "8",
            }
        )

        self.assertEqual(result, {"success": True})
        run_filter_workflow.assert_called_once_with(
            mode="low-score",
            limit=25,
            threshold=2.5,
            dry_run=True,
            mark_read=False,
            stream_id=None,
            incremental_mark=True,
            mark_batch_size=8,
        )

    @patch("rss_analyzer.feedly_handlers.process_stream")
    def test_process_stream_handler_coerces_transport_values(self, process_stream):
        process_stream.return_value = {"success": True}

        result = handle_process_stream(
            {"days": "7", "limit": "80", "export_markdown": "true"}
        )

        self.assertEqual(result, {"success": True})
        process_stream.assert_called_once_with(
            stream_id=None,
            stream_label=None,
            days=7,
            limit=80,
            strategy=None,
            export_markdown=True,
        )

    @patch("rss_analyzer.feedly_handlers.analyze_articles")
    def test_stream_analysis_passes_progress_callback(self, analyze_articles):
        analyze_articles.return_value = {"success": True}
        progress_callback = Mock()

        result = stream_run_analysis(
            {"limit": "4", "mark_read": "false", "refresh": "true"},
            progress_callback,
        )

        self.assertEqual(result, {"success": True})
        self.assertIs(
            analyze_articles.call_args.kwargs["progress_callback"],
            progress_callback,
        )
        self.assertEqual(analyze_articles.call_args.kwargs["limit"], 4)
        self.assertFalse(analyze_articles.call_args.kwargs["mark_read"])
        self.assertTrue(analyze_articles.call_args.kwargs["refresh"])

    @patch("rss_analyzer.feedly_handlers.process_stream", return_value={"success": True})
    @patch("rss_analyzer.feedly_handlers.run_filter_workflow", return_value={"success": True})
    @patch("rss_analyzer.feedly_handlers.analyze_articles", return_value={"success": True})
    def test_feedly_handlers_fallback_to_defaults_on_json_null(
        self, mock_analyze, mock_filter, mock_process
    ):
        from rss_analyzer.config import PROJ_CONFIG

        handle_run_analysis({"limit": None, "input_file": None})
        self.assertEqual(mock_analyze.call_args.kwargs["limit"], PROJ_CONFIG["limit"])
        self.assertEqual(mock_analyze.call_args.kwargs["input_file"], PROJ_CONFIG["input_file"])

        handle_run_filters({"mode": None, "limit": None, "threshold": None})
        self.assertEqual(mock_filter.call_args.kwargs["mode"], "all")
        self.assertEqual(mock_filter.call_args.kwargs["limit"], 1000)
        self.assertEqual(mock_filter.call_args.kwargs["threshold"], 3.0)

        handle_process_stream({"days": None, "limit": None})
        self.assertEqual(mock_process.call_args.kwargs["days"], 3)
        self.assertEqual(mock_process.call_args.kwargs["limit"], 500)

        stream_run_analysis({"limit": None}, Mock())
        self.assertEqual(mock_analyze.call_args.kwargs["limit"], PROJ_CONFIG["limit"])

        stream_process_stream({"days": None, "limit": None}, Mock())
        self.assertEqual(mock_process.call_args.kwargs["days"], 3)
        self.assertEqual(mock_process.call_args.kwargs["limit"], 500)

    @patch("rss_analyzer.vector_handlers.process_vector_index_queue", return_value={"processed": 0})
    @patch("rss_analyzer.vector_handlers.retry_vector_index_queue", return_value={"queued": 1})
    @patch("rss_analyzer.vector_handlers.get_vector_store")
    @patch("rss_analyzer.vector_handlers.is_vector_store_enabled", return_value=True)
    def test_vector_handlers_fallback_to_defaults_on_json_null(
        self, _mock_enabled, mock_get_store, _mock_retry, mock_process_queue
    ):
        store = Mock()
        store.search_similar.return_value = []
        store.discover_trending_topics.return_value = []
        mock_get_store.return_value = store

        handle_semantic_search({"query": "ai", "limit": None, "min_score": None})
        store.search_similar.assert_called_once_with("ai", 5, None)

        handle_discover_trending_topics({"limit": None, "sample_size": None, "hours": None})
        store.discover_trending_topics.assert_called_once_with(5, 100, 24)

        handle_retry_vector_indexing({"wait": True, "limit": None})
        mock_process_queue.assert_called_once_with(limit=100)


if __name__ == "__main__":
    unittest.main()
