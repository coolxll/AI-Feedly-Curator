import unittest
from unittest.mock import Mock, patch

from rss_analyzer.report_handlers import (
    REPORT_MESSAGE_HANDLERS,
    REPORT_STREAM_HANDLERS,
    handle_export_articles,
    stream_generate_daily_digest,
)


class TestReportHandlers(unittest.TestCase):
    def test_domain_registries_expose_report_operations(self):
        self.assertEqual(
            set(REPORT_MESSAGE_HANDLERS),
            {"export_articles", "generate_summary", "generate_daily_digest"},
        )
        self.assertEqual(
            set(REPORT_STREAM_HANDLERS), {"generate_daily_digest"}
        )

    def test_export_requires_output_file(self):
        self.assertEqual(
            handle_export_articles({}),
            {"error": "no_output_file", "message": "Output file is required"},
        )

    @patch("rss_analyzer.report_handlers.generate_daily_digest")
    def test_stream_digest_passes_progress_callback(self, mock_digest):
        mock_digest.return_value = {"success": True}
        callback = Mock()

        response = stream_generate_daily_digest(
            {"hours": "12", "top_n": "5"}, callback
        )

        self.assertTrue(response["success"])
        mock_digest.assert_called_once_with(
            stream_id=None,
            stream_label=None,
            hours=12,
            top_n=5,
            progress_callback=callback,
        )


if __name__ == "__main__":
    unittest.main()
