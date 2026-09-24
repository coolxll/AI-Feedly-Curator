import unittest
from unittest.mock import Mock, patch

from rss_analyzer.feedly_handlers import (
    FEEDLY_MESSAGE_HANDLERS,
    FEEDLY_STREAM_HANDLERS,
    handle_run_filters,
    handle_process_stream,
    stream_run_analysis,
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


if __name__ == "__main__":
    unittest.main()
