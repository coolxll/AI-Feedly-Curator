import unittest

from rss_analyzer.cache import build_vector_store_payload


class TestCacheVectorPayload(unittest.TestCase):
    def test_build_vector_store_payload_prefers_summary(self):
        payload = build_vector_store_payload(
            "article-1",
            4.5,
            {
                "title": "Test Title",
                "summary": "Summary text",
                "content": "Longer raw content",
                "url": "https://example.com/article",
            },
            "2026-03-26T12:00:00",
        )

        self.assertEqual(payload["article_id"], "article-1")
        self.assertIn("Title: Test Title", payload["document_text"])
        self.assertIn("Content: Summary text", payload["document_text"])
        self.assertNotIn("Longer raw content", payload["document_text"])
        self.assertEqual(payload["metadata"]["score"], 4.5)
        self.assertEqual(payload["metadata"]["url"], "https://example.com/article")
        self.assertEqual(payload["metadata"]["updated_at"], "2026-03-26T12:00:00")

    def test_build_vector_store_payload_returns_none_without_title_or_text(self):
        payload = build_vector_store_payload(
            "article-2",
            3.2,
            {},
        )
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
