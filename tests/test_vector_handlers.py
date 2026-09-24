import unittest
from unittest.mock import Mock, patch

from rss_analyzer.vector_handlers import (
    VECTOR_MESSAGE_HANDLERS,
    VECTOR_STREAM_HANDLERS,
    handle_get_article_tags,
    handle_retry_vector_indexing,
    handle_semantic_search,
    stream_rebuild_vector_store,
)


class TestVectorHandlers(unittest.TestCase):
    def test_domain_registries_expose_expected_operations(self):
        self.assertEqual(
            set(VECTOR_MESSAGE_HANDLERS),
            {
                "get_vector_index_queue",
                "retry_vector_indexing",
                "semantic_search",
                "get_article_tags",
                "discover_trending_topics",
                "delete_article",
                "clear_vector_store",
                "get_vector_store_stats",
                "rebuild_vector_store",
                "cleanup_invalid_entries",
            },
        )
        self.assertEqual(set(VECTOR_STREAM_HANDLERS), {"rebuild_vector_store"})

    @patch("rss_analyzer.vector_handlers.get_vector_store")
    @patch("rss_analyzer.vector_handlers.is_vector_store_enabled", return_value=True)
    def test_semantic_search_delegates_to_vector_store(
        self, mock_enabled, mock_get_vector_store
    ):
        vector_store = Mock()
        vector_store.search_similar.return_value = [{"article_id": "a-1"}]
        mock_get_vector_store.return_value = vector_store

        response = handle_semantic_search(
            {"query": "agent architecture", "limit": 3, "min_score": 0.6}
        )

        self.assertEqual(response["results"], [{"article_id": "a-1"}])
        vector_store.search_similar.assert_called_once_with(
            "agent architecture", 3, 0.6
        )

    def test_article_tags_requires_article_id(self):
        self.assertEqual(
            handle_get_article_tags({}),
            {"error": "no_article_id", "message": "Article ID is required"},
        )

    @patch("rss_analyzer.vector_handlers.process_vector_index_queue")
    @patch("rss_analyzer.vector_handlers.retry_vector_index_queue")
    def test_retry_vector_indexing_waits_when_requested(self, mock_retry, mock_process):
        mock_retry.return_value = {"retried": 2}
        mock_process.return_value = {"processed": 2}

        response = handle_retry_vector_indexing(
            {"wait": "true", "limit": "25"}
        )

        self.assertEqual(response, {"retried": 2, "processed": 2})
        mock_retry.assert_called_once_with(wake_worker=False)
        mock_process.assert_called_once_with(limit=25)

    @patch("rss_analyzer.vector_handlers.rebuild_vector_store")
    def test_stream_rebuild_passes_progress_callback(self, mock_rebuild):
        mock_rebuild.return_value = {"success": True}
        callback = Mock()

        response = stream_rebuild_vector_store({}, callback)

        self.assertTrue(response["success"])
        mock_rebuild.assert_called_once_with(progress_callback=callback)


if __name__ == "__main__":
    unittest.main()
