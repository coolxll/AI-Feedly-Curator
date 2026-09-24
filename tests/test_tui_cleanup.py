import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from rss_analyzer.tui.cleanup import (
    CleanupContext,
    execute_filter,
    run_filter_flow,
)


class _FakePrompt:
    def __init__(self, answer):
        self.answer = answer

    def ask(self):
        return self.answer


class TestTUICleanup(unittest.TestCase):
    def _context(self, backend=None, execute_filter_func=None):
        return CleanupContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_input=Mock(),
            execute_filter=execute_filter_func or Mock(),
        )

    def test_execute_filter_passes_requested_options(self):
        backend = Mock()
        backend.run_filter_workflow.return_value = {
            "article_count": 5,
            "filtered_count": 3,
            "remaining_count": 2,
        }
        context = self._context(backend=backend)

        execute_filter(
            context,
            "low-score",
            50,
            2.5,
            True,
            False,
            stream_id="feed/example",
            stream_label="Example",
        )

        backend.run_filter_workflow.assert_called_once_with(
            mode="low-score",
            limit=50,
            threshold=2.5,
            dry_run=True,
            mark_read=False,
            stream_id="feed/example",
        )

    def test_quick_cleanup_routes_through_injected_executor(self):
        executor = Mock()
        context = self._context(execute_filter_func=executor)
        fake_questionary = types.SimpleNamespace(
            Choice=lambda title, value=None: value,
            select=lambda *args, **kwargs: _FakePrompt("quick_all"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch.dict(
                os.environ,
                {
                    "CLEANUP_DEFAULT_LIMIT": "all",
                    "CLEANUP_DEFAULT_THRESHOLD": "3.0",
                    "CLEANUP_DEFAULT_MARK_READ": "true",
                },
            ):
                run_filter_flow(context)

        executor.assert_called_once_with("all", 0, 3.0, False, True)


if __name__ == "__main__":
    unittest.main()
