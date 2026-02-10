#!/usr/bin/env python3
"""
Complete migration script to move data from SQLite to ChromaDB vector store
This script ensures environment variables are loaded before importing modules
"""
import os
import sys
import sqlite3
import json
from dotenv import load_dotenv

# Add project root to path FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load environment variables BEFORE importing local modules
dotenv_path = os.path.join(project_root, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("✅ Environment variables loaded from .env")
else:
    print("⚠️ .env file not found")

# Verify API keys are available
api_keys = {
    'DASHSCOPE_API_KEY': os.getenv("DASHSCOPE_API_KEY"),
    'ALIYUN_OPENAI_API_KEY': os.getenv("ALIYUN_OPENAI_API_KEY"),
    'OPENAI_API_KEY': os.getenv("OPENAI_API_KEY")
}

available_keys = [k for k, v in api_keys.items() if v]
if available_keys:
    print(f"✅ Found API keys: {available_keys}")
else:
    print("❌ No API keys found - vector store operations will fail")
    print("   Please set one of: DASHSCOPE_API_KEY, ALIYUN_OPENAI_API_KEY, or OPENAI_API_KEY")

# Now import local modules after environment is set up
from rss_analyzer.cache import DB_PATH  # noqa: E402
from rss_analyzer.vector_store import vector_store  # noqa: E402


def migrate_from_sqlite_to_vector_store(batch_size=50):
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
    sqlite_cursor.execute(
        "SELECT article_id, score, data, title, url FROM article_scores"
    )

    migrated_count = 0
    skipped_count = 0
    batch = []

    for row in sqlite_cursor:
        article_id, score, data_str, title, url = row

        # Parse the data JSON
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            print(f"⚠️ Failed to parse JSON for article {article_id}, skipping...")
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
            success = vector_store.add_article(article_id, document_text, metadata)
            if not success:
                print(f"⚠️ Failed to add article {article_id} to vector store")
        except Exception as e:
            print(f"⚠️ Error adding article {article_id} to vector store: {e}")


def main():
    print("🚀 Complete Vector Store Migration Tool")
    print("=" * 50)

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

    # Clear vector store first
    print("🗑️ Clearing existing vector store data...")
    vector_store.clear_collection()
    print("✅ Vector store cleared")

    # Start migration
    migrate_from_sqlite_to_vector_store()

    # Verify migration
    print("\n🔍 Verifying migration results...")
    final_vector_count = vector_store.get_article_count()

    # Check a few random entries to verify they have title and URL
    all_ids = vector_store.get_all_article_ids()
    sample_ids = all_ids[:3] if len(all_ids) > 0 else []

    print(f"Sample verification from {len(sample_ids)} articles:")
    for sample_id in sample_ids:
        try:
            article_data = vector_store.collection.get(
                ids=[sample_id],
                include=['metadatas', 'documents']
            )
            if article_data['metadatas']:
                metadata = article_data['metadatas'][0]
                print(f"  - ID: {sample_id[:20]}...")
                print(f"    Title: {metadata.get('title', 'N/A')[:50]}...")
                print(f"    URL: {metadata.get('url', 'N/A')}")
                print(f"    Score: {metadata.get('score', 'N/A')}")
        except Exception as e:
            print(f"  - Error retrieving {sample_id}: {e}")

    print(f"\n🎯 Migration Summary:")
    print(f"   SQLite records: {sqlite_total}")
    print(f"   Vector store records: {final_vector_count}")


if __name__ == "__main__":
    main()