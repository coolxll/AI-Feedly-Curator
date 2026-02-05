import sys
import os
import logging
from dotenv import load_dotenv

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load env vars
load_dotenv(os.path.join(project_root, ".env"))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_vector_store():
    logger.info("Initializing vector store...")
    # Import here to ensure env vars are loaded first
    from rss_analyzer.vector_store import vector_store

    # 1. Test Adding Article
    article_id = "test_article_001"
    text = "This is a test article about artificial intelligence and machine learning. Vector databases are cool."
    metadata = {"title": "AI and Vector DBs", "category": "tech"}

    logger.info(f"Adding article: {article_id}")
    success = vector_store.add_article(article_id, text, metadata)

    if success:
        logger.info("Successfully added article.")
    else:
        logger.error("Failed to add article.")
        return

    # 2. Test Search
    query = "machine learning database"
    logger.info(f"Searching for: '{query}'")

    results = vector_store.search_similar(query, limit=1)

    logger.info("Search Results:")
    found = False
    for res in results:
        logger.info(res)
        if res["id"] == article_id:
            found = True

    if found:
        logger.info("TEST PASSED: Found the inserted article.")
    else:
        logger.error("TEST FAILED: Did not find the inserted article.")


if __name__ == "__main__":
    test_vector_store()
