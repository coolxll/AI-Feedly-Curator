import json
import importlib.util
import shutil
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(
    "C:/Workspace/Personal/rss-opml/skills/article-reading-report/scripts/build_reading_report.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("article_reading_report_skill", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestArticleReadingReportSkill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_classify_content_source_prefers_fetched_body(self):
        article = {
            "summary": "<p>short summary</p>",
            "content": "",
        }
        content, source, note = self.module.classify_content_source(
            article,
            "This is fetched body text " * 40,
            min_content_chars=100,
        )
        self.assertEqual(source, "fetched_body")
        self.assertGreater(len(content), 100)
        self.assertIsNone(note)

    def test_classify_content_source_falls_back_to_summary(self):
        article = {
            "summary": "<p>Useful summary text with enough detail for fallback.</p>",
            "content": "",
        }
        content, source, note = self.module.classify_content_source(
            article,
            "获取失败: HTTP 403",
            min_content_chars=100,
        )
        self.assertEqual(source, "summary_fallback")
        self.assertIn("Useful summary text", content)
        self.assertIn("Fell back", note)

    def test_prepare_article_record_contains_content_metadata(self):
        article = {
            "title": "Article A",
            "link": "https://example.com/a",
            "origin": "Source",
            "published": 1774489528000,
            "summary": "<p>Summary A</p>",
        }
        record = self.module.prepare_article_record(
            article,
            min_content_chars=100,
            fetched_text="Fetched content body " * 20,
        )
        self.assertEqual(record["content_source"], "fetched_body")
        self.assertEqual(record["content_source_label"], "正文")
        self.assertGreater(record["content_chars"], 100)
        self.assertGreaterEqual(record["estimated_read_minutes"], 1)

    def test_prepare_reading_packet_contains_counts(self):
        articles = [
            {
                "title": "Article A",
                "summary": "<p>Summary A</p>",
                "content": "Embedded content " * 20,
            },
            {
                "title": "Article B",
                "summary": "<p>Summary B</p>",
                "content": "",
            },
        ]

        original = self.module.prepare_article_record

        def fake_prepare(article, min_content_chars, fetched_text=None):
            if article["title"] == "Article A":
                return {
                    "title": "Article A",
                    "content_source": "embedded_content",
                    "content_source_label": "RSS全文",
                    "content": "x",
                    "content_chars": 100,
                    "estimated_read_minutes": 1,
                    "fallback_note": None,
                    "summary": "Summary A",
                    "link": "",
                    "origin": "",
                    "published": None,
                }
            return {
                "title": "Article B",
                "content_source": "summary_fallback",
                "content_source_label": "摘要回退",
                "content": "y",
                "content_chars": 50,
                "estimated_read_minutes": 1,
                "fallback_note": "fallback",
                "summary": "Summary B",
                "link": "",
                "origin": "",
                "published": None,
            }

        self.module.prepare_article_record = fake_prepare
        try:
            packet = self.module.prepare_reading_packet(articles, 100)
        finally:
            self.module.prepare_article_record = original

        self.assertEqual(packet["total_articles"], 2)
        self.assertEqual(packet["source_counts"]["RSS全文"], 1)
        self.assertEqual(packet["source_counts"]["摘要回退"], 1)
        self.assertEqual(len(packet["records"]), 2)

    def test_render_sources_markdown_contains_links(self):
        packet = {
            "generated_at": "2026-03-26 10:00:00",
            "total_articles": 1,
            "records": [
                {
                    "title": "Article A",
                    "link": "https://example.com/a",
                    "origin": "Source",
                    "content_source_label": "正文",
                    "estimated_read_minutes": 2,
                    "fallback_note": None,
                    "summary": "Summary A",
                }
            ],
        }
        md = self.module.render_sources_markdown(Path("export.json"), packet)
        self.assertIn("[Article A](https://example.com/a)", md)
        self.assertEqual(self.module.escape_markdown_link_text("[AI] title"), "\\[AI\\] title")
        self.assertIn("Evidence", md)

    def test_save_outputs_uses_run_directory_and_stable_filenames(self):
        packet = {
            "generated_at": "2026-03-26 10:00:00",
            "total_articles": 1,
            "source_counts": {"正文": 1},
            "records": [],
        }

        original_datetime = self.module.datetime
        test_output_dir = Path("output/test-reading-report-skill")

        class FixedDateTime:
            @staticmethod
            def now():
                return datetime(2026, 3, 26, 12, 34, 56)

        if test_output_dir.exists():
            shutil.rmtree(test_output_dir)

        self.module.datetime = FixedDateTime
        try:
            json_path, md_path = self.module.save_outputs(
                test_output_dir,
                Path("export_20260326_094947.json"),
                packet,
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        finally:
            self.module.datetime = original_datetime
            if test_output_dir.exists():
                shutil.rmtree(test_output_dir)

        self.assertEqual(json_path.parent.name, "20260326-123456")
        self.assertEqual(json_path.name, "reading-packet.json")
        self.assertEqual(md_path.parent, json_path.parent)
        self.assertEqual(md_path.name, "reading-sources.md")
        self.assertEqual(payload["input_file"], "export_20260326_094947.json")
        self.assertEqual(payload["run_id"], "20260326-123456")
        self.assertEqual(payload["total_articles"], 1)


if __name__ == "__main__":
    unittest.main()
