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


if __name__ == "__main__":
    unittest.main()
