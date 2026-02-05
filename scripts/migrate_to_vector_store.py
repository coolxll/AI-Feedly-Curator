#!/usr/bin/env python3
"""
Vector Store Migration Script

This script migrates historical data from SQLite database to ChromaDB vector store.
"""

import json
import logging
import os
import sqlite3
import sys
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv(os.path.join(project_root, ".env"))

# Need to set up path before importing local modules
from rss_analyzer.cache import DB_PATH  # noqa: E402
from rss_analyzer.vector_store import vector_store  # noqa: E402


def migrate_from_sqlite_to_vector_store(batch_size=100):
    """Migrate data from SQLite to vector store in batches"""
    print("🔄 Starting migration from SQLite to vector store...")

    # Get current counts
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()

    sqlite_cursor.execute("SELECT COUNT(*) FROM article_scores")
    sqlite_total = sqlite_cursor.fetchone()[0]
    vector_count = vector_store.get_article_count()

    print(f"📊 SQLite records: {sqlite_total}")
    print(f"📊 Vector store records: {vector_count}")

    # Get all records from SQLite
    sqlite_cursor.execute("SELECT article_id, score, data, title, url, updated_at FROM article_scores")

    migrated_count = 0
    skipped_count = 0
    batch = []

    for row in sqlite_cursor:
        article_id, score, data_str, title, url, updated_at = row

        # Parse the data JSON
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON for article {article_id}, skipping...")
            skipped_count += 1
            continue

        # Enhance data with title and URL from separate columns if not in data
        if not data.get("title") and title and title.strip():
            data["title"] = title
        if not data.get("url") and url and url.strip():
            data["url"] = url

        # Try to extract title and URL from the data dictionary if they exist
        article_title = data.get("title", "") or title or ""
        article_url = data.get("url", "") or url or ""

        # Use summary or content for the embedding text
        text_content = data.get("summary") or data.get("content") or ""

        # Only proceed if we have meaningful content to embed
        if not text_content.strip() and not article_title.strip():
            # Skip if both content and title are empty
            skipped_count += 1
            continue

        # Construct document for embedding
        document_text = ""
        if article_title.strip():
            document_text += f"Title: {article_title}\n"
        if text_content.strip():
            document_text += f"Content: {text_content}"

        if document_text.strip():  # Only add if there's content
            # Prepare metadata
            metadata = {
                "score": score,
                "title": article_title[:100] if article_title.strip() else "Untitled",  # Limit length
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
            }

            if article_url.strip():
                metadata["url"] = article_url

            batch.append((article_id, document_text, metadata))

        # Process batch when it reaches the specified size
        if len(batch) >= batch_size:
            process_batch(batch)
            migrated_count += len(batch)
            batch = []
            print(f"   Processed {migrated_count}/{sqlite_total} records...")

    # Process remaining items in the last batch
    if batch:
        process_batch(batch)
        migrated_count += len(batch)
        print(f"   Processed {migrated_count}/{sqlite_total} records...")

    sqlite_conn.close()

    # Final counts
    new_vector_count = vector_store.get_article_count()
    print("\n✅ Migration completed!")
    print(f"📊 Records migrated: {migrated_count}")
    print(f"📊 Records skipped: {skipped_count}")
    print(f"📊 Vector store final count: {new_vector_count}")


def process_batch(batch):
    """Process a batch of articles and add to vector store"""
    for article_id, document_text, metadata in batch:
        try:
            # Add to vector store
            vector_store.add_article(article_id, document_text, metadata)
        except Exception as e:
            logger.error(f"Failed to add article {article_id} to vector store: {e}")


def main():
    print("🚀 Vector Store Migration Tool")
    print("="*50)

    # Show current status
    vector_count = vector_store.get_article_count()
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute("SELECT COUNT(*) FROM article_scores")
    sqlite_total = sqlite_cursor.fetchone()[0]
    sqlite_conn.close()

    print("Current status:")
    print(f"  - SQLite records: {sqlite_total}")
    print(f"  - Vector store records: {vector_count}")
    print()

    if vector_count >= sqlite_total:
        print("ℹ️  Vector store already has equal or more records than SQLite. Migration may not be needed.")
        return

    confirm = input(f"⚠️  This will migrate {sqlite_total} records to vector store. Continue? (y/N): ")
    if confirm.lower() == 'y':
        migrate_from_sqlite_to_vector_store()
    else:
        print("   Migration cancelled.")


if __name__ == "__main__":
    main()