import unittest
from unittest.mock import Mock

from rss_analyzer.tui.reports import (
    ReportContext,
    execute_analyze,
    execute_export,
)


class TestTUIReports(unittest.TestCase):
    def _context(self, backend):
        return ReportContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
        )

    def test_execute_export_resolves_path_and_calls_backend(self):
        backend = Mock()
        backend.export_articles.return_value = {
            "article_count": 2,
            "output_file": "output/articles.json",
        }
        context = self._context(backend)

        execute_export(context, 20, "feed/example", "articles.json", "Example")

        backend.export_articles.assert_called_once_with(
            limit=20,
            output_file="output/articles.json",
            stream_id="feed/example",
        )

    def test_execute_analyze_passes_requested_options(self):
        backend = Mock()
        backend.analyze_articles.return_value = {
            "analyzed_file": "output/analyzed.json",
            "summary_file": "output/summary.md",
        }
        context = self._context(backend)

        execute_analyze(
            context,
            50,
            True,
            False,
            stream_id="feed/example",
            threads=4,
            stream_label="Example",
        )

        backend.analyze_articles.assert_called_once_with(
            limit=50,
            refresh=True,
            mark_read=False,
            stream_id="feed/example",
            threads=4,
        )


if __name__ == "__main__":
    unittest.main()
