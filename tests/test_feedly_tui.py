import sys
import types
import unittest
from unittest.mock import patch

import feedly_tui


class _FakeChoice:
    def __init__(self, title, value=None):
        self.title = title
        self.value = value


def _fake_separator(value):
    return value


def _fake_style(value):
    return value


class _FakePrompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class TestFeedlyTUI(unittest.TestCase):
    def test_select_stream_interactive_maps_global_choice_back_to_none(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            Separator=_fake_separator,
            Style=_fake_style,
            select=lambda *args, **kwargs: _FakePrompt(feedly_tui.GLOBAL_STREAM_SENTINEL),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.feedly_get_categories", return_value=[{"id": "cat/1", "label": "Tech"}]):
                with patch("feedly_tui.feedly_get_subscriptions", return_value=[{"id": "feed/1", "title": "Feed 1"}]):
                    with patch(
                        "feedly_tui.feedly_get_unread_counts",
                        return_value={
                            "unreadcounts": [
                                {"id": "user/123/category/global.all", "count": 413}
                            ]
                        },
                    ):
                        stream_id, stream_label = feedly_tui.select_stream_interactive()

        self.assertIsNone(stream_id)
        self.assertEqual(stream_label, "Global All")

    def test_select_stream_interactive_keeps_manual_stream_id(self):
        answers = iter(["MANUAL", "feed/http://example.com/rss"])
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            Separator=_fake_separator,
            Style=_fake_style,
            select=lambda *args, **kwargs: _FakePrompt(next(answers)),
            text=lambda *args, **kwargs: _FakePrompt(next(answers)),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.feedly_get_categories", return_value=[{"id": "cat/1", "label": "Tech"}]):
                with patch("feedly_tui.feedly_get_subscriptions", return_value=[{"id": "feed/1", "title": "Feed 1"}]):
                    with patch(
                        "feedly_tui.feedly_get_unread_counts",
                        return_value={"unreadcounts": []},
                    ):
                        stream_id, stream_label = feedly_tui.select_stream_interactive()

        self.assertEqual(stream_id, "feed/http://example.com/rss")
        self.assertEqual(stream_label, "Manual ID: feed/http://example.com/rss")

    def test_run_review_menu_routes_quick_review(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("quick"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.run_process_stream_flow") as mock_quick:
                with patch("feedly_tui.run_batch_read_flow") as mock_batch:
                    feedly_tui.run_review_menu()

        mock_quick.assert_called_once()
        mock_batch.assert_not_called()

    def test_run_review_menu_routes_batch_read(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("batch"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.run_process_stream_flow") as mock_quick:
                with patch("feedly_tui.run_batch_read_flow") as mock_batch:
                    feedly_tui.run_review_menu()

        mock_quick.assert_not_called()
        mock_batch.assert_called_once()

    def test_run_reports_menu_routes_analyze(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("analyze"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.run_analyze_flow") as mock_analyze:
                with patch("feedly_tui.run_summary_flow") as mock_summary:
                    feedly_tui.run_reports_menu()

        mock_analyze.assert_called_once()
        mock_summary.assert_not_called()

    def test_run_reports_menu_routes_quick_analyze(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("quick_analyze"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.execute_analyze") as mock_exec:
                feedly_tui.run_reports_menu()

        mock_exec.assert_called_once_with(
            limit=100, refresh=True, mark_read=False, stream_id=None, threads=3
        )

    def test_run_filter_flow_quick_all_executes_with_defaults(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("quick_all"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch.dict(
                "os.environ",
                {
                    "CLEANUP_DEFAULT_LIMIT": "999",
                    "CLEANUP_DEFAULT_THRESHOLD": "3.0",
                    "CLEANUP_DEFAULT_MARK_READ": "true",
                },
                clear=False,
            ):
                with patch("feedly_tui.execute_filter") as mock_filter:
                    feedly_tui.run_filter_flow()

        mock_filter.assert_called_once_with(
            "all", 999, 3.0, False, True
        )


if __name__ == "__main__":
    unittest.main()
