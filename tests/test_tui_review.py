import sys
import types
import unittest
from unittest.mock import Mock, patch

from rss_analyzer.tui.review import (
    ReviewContext,
    execute_batch_read,
    execute_process_stream,
    open_stream_article,
)


class _FakePrompt:
    def __init__(self, answer):
        self.answer = answer

    def ask(self):
        return self.answer


class TestTUIReview(unittest.TestCase):
    def _context(self, backend):
        return ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
        )

    def test_execute_process_stream_calls_backend_without_optional_actions(self):
        backend = Mock()
        backend.process_stream.return_value = {
            "strategy": "radar",
            "article_count": 0,
            "fetched_count": 0,
            "summary": "No unread articles.",
            "digest": {},
            "mark_read_candidates": [],
            "markdown": "",
        }
        context = self._context(backend)
        fake_questionary = types.SimpleNamespace(
            confirm=lambda *args, **kwargs: _FakePrompt(False),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            execute_process_stream(
                context,
                "feed/example",
                limit=25,
                days=7,
                stream_label="Example",
            )

        backend.process_stream.assert_called_once_with(
            stream_id="feed/example",
            stream_label="Example",
            days=7,
            limit=25,
        )
        backend.mark_stream_low_priority_read.assert_not_called()

    def test_execute_batch_read_stops_when_backlog_is_empty(self):
        backend = Mock()
        backend.process_batch.return_value = {"fetched_count": 0}
        context = self._context(backend)
        fake_questionary = types.SimpleNamespace()

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            execute_batch_read(context, None, batch_size=20, days=3)

        backend.process_batch.assert_called_once_with(
            stream_id=None,
            stream_label=None,
            batch_size=20,
            days=3,
        )

    @patch("rss_analyzer.tui.review.webbrowser.open", return_value=True)
    def test_open_stream_article_uses_default_browser(self, browser_open):
        context = self._context(Mock())

        self.assertTrue(
            open_stream_article(context, {"link": "https://example.com/article"})
        )
        browser_open.assert_called_once_with("https://example.com/article")


if __name__ == "__main__":
    unittest.main()
