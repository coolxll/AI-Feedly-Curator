import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

import feedly_tui
from rss_analyzer.tui.reports import (
    ReportContext,
    run_summary_flow as reports_run_summary_flow,
)
from rss_analyzer.tui.review import (
    ReviewContext,
    execute_batch_read as review_execute_batch_read,
    execute_process_stream as review_execute_process_stream,
    loop_open_articles as review_loop_open_articles,
    run_batch_read_flow as review_run_batch_read_flow,
)


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

    def test_run_review_menu_routes_quick_default(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("quick_default"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.execute_process_stream") as mock_exec:
                feedly_tui.run_review_menu()

        mock_exec.assert_called_once_with(
            stream_id=None,
            limit=500,
            days=3,
            stream_label="Global All",
        )

    def test_run_review_menu_routes_batch_default(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("batch_default"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.execute_batch_read") as mock_exec:
                feedly_tui.run_review_menu()

        mock_exec.assert_called_once_with(
            stream_id=None,
            stream_label="Global All",
            batch_size=50,
            days=3,
        )

    def test_get_review_defaults_env_overrides(self):
        with patch.dict(
            os.environ,
            {
                "REVIEW_DEFAULT_LIMIT": "200",
                "REVIEW_DEFAULT_DAYS": "7",
                "REVIEW_DEFAULT_CHUNK_SIZE": "25",
            },
        ):
            limit, days, chunk = feedly_tui._get_review_defaults()
            self.assertEqual(limit, 200)
            self.assertEqual(days, 7)
            self.assertEqual(chunk, 25)

        with patch.dict(os.environ, {"REVIEW_DEFAULT_LIMIT": "all"}):
            limit, _, _ = feedly_tui._get_review_defaults()
            self.assertEqual(limit, 0)

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

    def test_run_filter_flow_quick_all_executes_with_full_unread_limit(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("quick_all"),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch.dict(
                "os.environ",
                {
                    "CLEANUP_DEFAULT_LIMIT": "all",
                    "CLEANUP_DEFAULT_THRESHOLD": "3.0",
                    "CLEANUP_DEFAULT_MARK_READ": "true",
                },
                clear=False,
            ):
                with patch("feedly_tui.execute_filter") as mock_filter:
                    feedly_tui.run_filter_flow()

        mock_filter.assert_called_once_with(
            "all", 0, 3.0, False, True
        )

    def test_main_menu_exits_when_cancelled(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            Style=_fake_style,
            select=lambda *args, **kwargs: _FakePrompt(None),
        )
        fake_prompt_toolkit = types.SimpleNamespace()

        with patch.dict(
            sys.modules,
            {"questionary": fake_questionary, "prompt_toolkit": fake_prompt_toolkit},
        ):
            with patch.object(feedly_tui.console, "clear"):
                with patch.object(feedly_tui.console, "print"):
                    feedly_tui.main_menu()

    def test_select_stream_interactive_returns_none_tuple_on_cancel(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            Separator=_fake_separator,
            Style=_fake_style,
            select=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.feedly_get_categories", return_value=[{"id": "cat/1", "label": "Tech"}]):
                with patch("feedly_tui.feedly_get_subscriptions", return_value=[{"id": "feed/1", "title": "Feed 1"}]):
                    with patch(
                        "feedly_tui.feedly_get_unread_counts",
                        return_value={"unreadcounts": []},
                    ):
                        stream_id, stream_label = feedly_tui.select_stream_interactive()

        self.assertIsNone(stream_id)
        self.assertIsNone(stream_label)

    def test_run_summary_flow_returns_early_on_cancel(self):
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("rss_analyzer.tui.reports.execute_analyze") as mock_analyze:
                feedly_tui.run_summary_flow()

        mock_analyze.assert_not_called()

    def test_run_export_flow_returns_early_when_filename_cancelled(self):
        fake_questionary = types.SimpleNamespace(
            confirm=lambda *args, **kwargs: _FakePrompt(False),
            text=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("rss_analyzer.tui.reports.execute_export") as mock_export:
                feedly_tui.run_export_flow()

        mock_export.assert_not_called()

    def test_run_analyze_flow_aborts_when_stream_selection_cancelled(self):
        confirm_answers = iter([True, True])
        fake_questionary = types.SimpleNamespace(
            text=lambda *args, **kwargs: _FakePrompt("50"),
            confirm=lambda *args, **kwargs: _FakePrompt(next(confirm_answers)),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.select_stream_interactive", return_value=(None, None)):
                with patch("rss_analyzer.tui.reports.execute_analyze") as mock_analyze:
                    feedly_tui.run_analyze_flow()

        mock_analyze.assert_not_called()

    def test_run_filter_flow_aborts_when_stream_selection_cancelled(self):
        select_answers = iter(["custom", "all"])
        text_answers = iter(["50", "3.0"])
        confirm_answers = iter([False, True])
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt(next(select_answers)),
            text=lambda *args, **kwargs: _FakePrompt(next(text_answers)),
            confirm=lambda *args, **kwargs: _FakePrompt(next(confirm_answers)),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.select_stream_interactive", return_value=(None, None)):
                with patch("feedly_tui.execute_filter") as mock_filter:
                    feedly_tui.run_filter_flow()

        mock_filter.assert_not_called()

    def test_run_filter_flow_aborts_when_limit_prompt_cancelled(self):
        select_answers = iter(["custom", "all"])
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt(next(select_answers)),
            text=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("feedly_tui.execute_filter") as mock_filter:
                feedly_tui.run_filter_flow()

        mock_filter.assert_not_called()

    def test_execute_batch_read_exits_when_action_cancelled(self):
        backend = Mock()
        backend.process_batch.return_value = {
            "strategy": "batch",
            "article_count": 1,
            "fetched_count": 1,
            "summary": "Batch summary",
            "digest": {},
            "mark_read_candidates": [],
        }
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
        )
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            review_execute_batch_read(context, None, batch_size=10, days=3)

        backend.process_batch.assert_called_once()

    def test_run_batch_read_flow_returns_early_on_cancel(self):
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
        )
        fake_questionary = types.SimpleNamespace(
            confirm=lambda *args, **kwargs: _FakePrompt(False),
            text=lambda *args, **kwargs: _FakePrompt(None),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("rss_analyzer.tui.review.execute_batch_read") as mock_exec:
                review_run_batch_read_flow(context)

        mock_exec.assert_not_called()

    def test_simple_batch_read_works_without_questionary(self):
        backend = Mock()
        backend.process_batch.return_value = {
            "strategy": "batch",
            "article_count": 1,
            "fetched_count": 1,
            "summary": "Batch summary",
            "digest": {},
            "mark_read_candidates": ["a1"],
        }
        inputs = iter(["", "20", "5", "5"])
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
            get_input=lambda prompt, default=None: next(inputs),
        )

        with patch.dict(sys.modules, {"questionary": None}):
            review_run_batch_read_flow(context)

        backend.process_batch.assert_called_once_with(
            stream_id=None,
            stream_label="全量未读 (Global All)",
            batch_size=20,
            days=5,
        )

    def test_simple_review_menu_routes_batch_choices_in_simple_mode(self):
        choices = iter(["2", "4", "5"])
        with patch("feedly_tui.get_input", side_effect=lambda *a, **kw: next(choices)):
            with patch("feedly_tui.execute_batch_read") as mock_exec_batch:
                with patch("feedly_tui.run_batch_read_flow") as mock_run_batch:
                    with patch.object(feedly_tui.console, "print"):
                        feedly_tui.simple_review_menu()

        mock_exec_batch.assert_called_once_with(
            stream_id=None,
            stream_label="Global All",
            batch_size=50,
            days=3,
            simple=True,
        )
        mock_run_batch.assert_called_once_with(simple=True)

    def test_run_summary_flow_handles_backend_error_dict(self):
        backend = Mock()
        backend.generate_summary_report.return_value = {
            "error": "summary_failed",
            "message": "LLM unavailable",
        }
        console = Mock()
        context = ReportContext(
            console=console,
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
        )
        fake_questionary = types.SimpleNamespace(
            Choice=_FakeChoice,
            select=lambda *args, **kwargs: _FakePrompt("local"),
            confirm=lambda *args, **kwargs: _FakePrompt(False),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("rss_analyzer.tui.reports.load_articles", return_value=[{"title": "A"}]):
                reports_run_summary_flow(context)

        context.logger.exception.assert_not_called()

    def test_execute_process_stream_handles_error_result_without_crashing(self):
        backend = Mock()
        backend.process_stream.return_value = {
            "error": "auth_failed",
            "message": "Token expired",
        }
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
        )

        review_execute_process_stream(context, None, limit=10, days=3)

        context.logger.exception.assert_not_called()

    def test_execute_batch_read_clears_mark_read_ids_after_mark_clear_succeeds(self):
        backend = Mock()
        backend.process_batch.return_value = {
            "strategy": "batch",
            "article_count": 2,
            "fetched_count": 2,
            "summary": "Batch summary",
            "digest": {},
            "mark_read_candidates": ["a1", "a2"],
        }
        backend.mark_articles_read.return_value = {"success": True, "marked_count": 2}
        # Select mark_clear ("2") twice, then exit ("5")
        inputs = iter(["2", "2", "5"])
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(return_value=backend),
            select_stream_interactive=Mock(return_value=(None, "Global All")),
            get_review_defaults=Mock(return_value=(500, 3, 50)),
            get_input=lambda prompt, default=None: next(inputs),
        )

        review_execute_batch_read(context, None, batch_size=10, days=3, simple=True)

        # mark_articles_read should only be called once, not twice
        backend.mark_articles_read.assert_called_once_with(["a1", "a2"])

    def test_loop_open_articles_disambiguates_duplicate_titles_and_non_numeric_score(self):
        digest = {
            "deep_analyzed_reads": [
                {"title": "Same Title", "link": "https://example.com/1", "score": "N/A"},
                {"title": "Same Title", "link": "https://example.com/2", "score": 4.5},
            ],
            "skim_items": [],
        }
        seen_choices = []

        def fake_select(message, choices):
            seen_choices.append(list(choices))
            if len(seen_choices) == 1:
                # Pick the first duplicate title
                return _FakePrompt(choices[0])
            # Done reading
            return _FakePrompt(choices[-1])

        fake_questionary = types.SimpleNamespace(select=fake_select)
        context = ReviewContext(
            console=Mock(),
            logger=Mock(),
            load_backend_service=Mock(),
            select_stream_interactive=Mock(),
            get_review_defaults=Mock(),
        )

        with patch.dict(sys.modules, {"questionary": fake_questionary}):
            with patch("rss_analyzer.tui.review.webbrowser.open", return_value=True) as mock_open:
                review_loop_open_articles(context, digest, simple=False)

        # First call choices must have distinct indexed labels for both articles
        self.assertTrue(seen_choices[0][0].startswith("1. "))
        self.assertTrue(seen_choices[0][1].startswith("2. "))
        self.assertIn("[N/A]", seen_choices[0][0])
        self.assertIn("[4.5]", seen_choices[0][1])
        mock_open.assert_called_once_with("https://example.com/1")


if __name__ == "__main__":
    unittest.main()
