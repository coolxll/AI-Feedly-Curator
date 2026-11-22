import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rss_analyzer.report_handlers import (
    REPORT_MESSAGE_HANDLERS,
    REPORT_STREAM_HANDLERS,
    handle_export_articles,
    handle_generate_daily_digest,
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

    @patch("rss_analyzer.report_handlers.export_articles")
    def test_export_confines_output_file_to_allowed_output_dir(self, mock_export):
        mock_export.return_value = {"success": True}
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_dir = Path(tmpdir) / "output"
            allowed_dir.mkdir()
            valid_target = allowed_dir / "nested" / "export.json"

            with patch("rss_analyzer.report_handlers.EXPORT_OUTPUT_DIR", allowed_dir):
                response = handle_export_articles(
                    {"output_file": str(valid_target), "limit": 25}
                )

            self.assertTrue(response["success"])
            mock_export.assert_called_once_with(
                limit=25,
                output_file=str(valid_target.resolve()),
                stream_id=None,
            )

    @patch("rss_analyzer.report_handlers.export_articles")
    def test_export_rejects_traversal_absolute_and_symlink_escape(self, mock_export):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            allowed_dir = base / "output"
            outside_dir = base / "outside"
            allowed_dir.mkdir()
            outside_dir.mkdir()
            outside_file = outside_dir / "secret.json"

            symlink_escape = allowed_dir / "escape.json"
            os.symlink(outside_file, symlink_escape)

            with patch("rss_analyzer.report_handlers.EXPORT_OUTPUT_DIR", allowed_dir):
                for bad_path in (
                    str(allowed_dir / ".." / "outside" / "secret.json"),
                    str(outside_file),
                    "/etc/passwd",
                    str(symlink_escape),
                    str(allowed_dir),
                ):
                    result = handle_export_articles({"output_file": bad_path})
                    self.assertEqual(result.get("error"), "invalid_output_file", bad_path)

            mock_export.assert_not_called()

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

    @patch("rss_analyzer.report_handlers.generate_daily_digest", return_value={"success": True})
    @patch("rss_analyzer.report_handlers.export_articles", return_value={"success": True})
    def test_report_handlers_fallback_to_defaults_on_json_null(
        self, mock_export, mock_digest
    ):
        from rss_analyzer.config import PROJ_CONFIG

        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_dir = Path(tmpdir) / "output"
            allowed_dir.mkdir()
            valid_target = allowed_dir / "export.json"
            with patch("rss_analyzer.report_handlers.EXPORT_OUTPUT_DIR", allowed_dir):
                handle_export_articles({"output_file": str(valid_target), "limit": None})
            self.assertEqual(mock_export.call_args.kwargs["limit"], PROJ_CONFIG["limit"])

        handle_generate_daily_digest({"hours": None, "top_n": None})
        self.assertEqual(mock_digest.call_args.kwargs["hours"], 24)
        self.assertEqual(mock_digest.call_args.kwargs["top_n"], 10)

        stream_generate_daily_digest({"hours": None, "top_n": None}, Mock())
        self.assertEqual(mock_digest.call_args.kwargs["hours"], 24)
        self.assertEqual(mock_digest.call_args.kwargs["top_n"], 10)


class TestGenerateDailyDigest(unittest.TestCase):
    @patch("rss_analyzer.report_service.save_stream_overview_markdown", return_value="output/digest.md")
    @patch("rss_analyzer.report_service.iter_cached_scores")
    def test_handles_none_score_none_summary_and_aware_timestamps(
        self, mock_iter_scores, mock_save_md
    ):
        from datetime import datetime, timedelta, timezone
        from rss_analyzer.report_service import generate_daily_digest

        now_utc = datetime.now(timezone.utc)
        now_naive = datetime.now()
        mock_iter_scores.return_value = [
            {
                "article_id": "a-high",
                "score": 4.2,
                "data": {"title": "High", "summary": None, "comment": None},
                "updated_at": now_utc.isoformat(),
            },
            {
                "article_id": "a-none-score",
                "score": None,
                "data": {"title": "No Score", "summary": "Body"},
                "updated_at": now_naive.isoformat(),
            },
            {
                "article_id": "a-old",
                "score": 4.9,
                "data": {"title": "Old"},
                "updated_at": (now_utc - timedelta(hours=48)).isoformat(),
            },
        ]

        result = generate_daily_digest(hours=24, top_n=10)

        self.assertTrue(result["success"])
        self.assertEqual(result["article_count"], 2)
        self.assertEqual(result["must_read_count"], 1)
        self.assertEqual(result["low_count"], 1)
        self.assertIn("High (score: 4.2)", result["markdown"])
        mock_save_md.assert_called_once()

    @patch("rss_analyzer.report_service.save_stream_overview_markdown", return_value="output/digest.md")
    @patch("rss_analyzer.report_service.iter_cached_scores")
    def test_filters_by_stream_id_when_stream_metadata_present(
        self, mock_iter_scores, mock_save_md
    ):
        from datetime import datetime, timezone
        from rss_analyzer.report_service import generate_daily_digest

        now_iso = datetime.now(timezone.utc).isoformat()
        mock_iter_scores.return_value = [
            {
                "article_id": "a-1",
                "score": 4.5,
                "data": {"title": "From Feed A", "origin_stream_id": "feed/a"},
                "updated_at": now_iso,
            },
            {
                "article_id": "a-2",
                "score": 4.6,
                "data": {"title": "From Feed B", "stream_id": "feed/b"},
                "updated_at": now_iso,
            },
        ]

        result = generate_daily_digest(stream_id="feed/a", hours=24, top_n=10)

        self.assertTrue(result["success"])
        self.assertEqual(result["article_count"], 1)
        self.assertIn("From Feed A", result["markdown"])
        self.assertNotIn("From Feed B", result["markdown"])


if __name__ == "__main__":
    unittest.main()
