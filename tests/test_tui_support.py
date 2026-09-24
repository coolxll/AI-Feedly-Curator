import os
import unittest
from unittest.mock import patch

from rss_analyzer.tui.support import (
    filter_articles_by_titles,
    format_limit_display,
    get_cleanup_defaults,
    resolve_export_path,
    resolve_stream_feed_titles,
)


class TestTUISupport(unittest.TestCase):
    def test_resolve_export_path_places_bare_filename_under_output(self):
        self.assertEqual(resolve_export_path("articles.json"), "output/articles.json")
        self.assertEqual(resolve_export_path("tmp/articles.json"), "tmp/articles.json")

    def test_limit_display_handles_full_unread_sentinel(self):
        self.assertEqual(format_limit_display(0), "All (全量)")
        self.assertEqual(format_limit_display(None), "All (全量)")
        self.assertEqual(format_limit_display(25), "25")

    def test_cleanup_defaults_parse_environment_values(self):
        with patch.dict(
            os.environ,
            {
                "CLEANUP_DEFAULT_LIMIT": "all",
                "CLEANUP_DEFAULT_THRESHOLD": "2.75",
                "CLEANUP_DEFAULT_MARK_READ": "off",
            },
        ):
            self.assertEqual(get_cleanup_defaults(), (0, 2.75, False))

    def test_stream_title_resolution_and_article_filtering(self):
        categories = [{"id": "category/tech", "label": "Tech"}]
        subscriptions = [
            {
                "id": "feed/one",
                "title": "One",
                "categories": [{"id": "category/tech"}],
            },
            {"id": "feed/two", "title": "Two", "categories": []},
        ]

        titles = resolve_stream_feed_titles(
            "category/tech",
            categories=categories,
            subscriptions=subscriptions,
        )
        articles = [{"origin": "One"}, {"origin": "Two"}]

        self.assertEqual(titles, ["One"])
        self.assertEqual(filter_articles_by_titles(articles, titles), [{"origin": "One"}])


if __name__ == "__main__":
    unittest.main()
