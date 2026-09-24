#!/usr/bin/env python3
"""
Clean Start Script

This script clears both SQLite database and ChromaDB vector store
to start fresh data accumulation.
"""

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
from rss_analyzer.cache import DB_PATH, init_db  # noqa: E402
from rss_analyzer.vector_store import vector_store  # noqa: E402


def clean_start():
    """Reset both databases to start fresh"""
    print("🔄 Starting clean slate process...")

    # 1. Clear SQLite database
    print("\n🗑️  Clearing SQLite database...")
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get current count
        cursor.execute("SELECT COUNT(*) FROM article_scores")
        count = cursor.fetchone()[0]
        print(f"   Found {count} records in SQLite")

        cursor.execute("DELETE FROM article_scores")
        cursor.execute("DELETE FROM app_cache")
        cursor.execute("DELETE FROM vector_index_outbox")

        conn.commit()
        conn.close()
        print("   ✅ SQLite database cleared and tables re-initialized")
    except Exception as e:
        print(f"   ❌ Error clearing SQLite: {e}")
        return False

    # 2. Clear Vector Store
    print("\n🗑️  Clearing Vector Store...")
    try:
        initial_count = vector_store.get_article_count()
        print(f"   Found {initial_count} records in vector store")

        success = vector_store.clear_collection()
        if success:
            final_count = vector_store.get_article_count()
            print(f"   ✅ Vector store cleared. Remaining: {final_count}")
        else:
            print("   ❌ Failed to clear vector store")
            return False
    except Exception as e:
        print(f"   ❌ Error clearing vector store: {e}")
        return False

    # 3. Note: We don't clear the ChromaDB directory here as it may be locked by the persistent client
    # The clear_collection() above should be sufficient for clearing the data
    print(
        "\n🗑️  ChromaDB data cleared via collection API (directory left intact to avoid lock issues)"
    )

    print("\n🎉 Clean start completed successfully!")
    print("Both databases are now empty and ready for fresh data accumulation.")
    return True


def main():
    print("🚀 Clean Start Tool")
    print("=" * 50)

    # Show current status
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM article_scores")
        sqlite_count = cursor.fetchone()[0]
        conn.close()
    except Exception:
        sqlite_count = 0

    try:
        vector_count = vector_store.get_article_count()
    except Exception:
        vector_count = 0

    print("Current status:")
    print(f"  - SQLite records: {sqlite_count}")
    print(f"  - Vector store records: {vector_count}")
    print()

    # Automatically confirm in non-interactive mode
    success = clean_start()
    if success:
        print("\n✨ Both databases are now ready for fresh data accumulation!")
    else:
        print("\n❌ Clean start process failed.")


if __name__ == "__main__":
    main()
