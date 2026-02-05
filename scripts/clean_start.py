#!/usr/bin/env python3
"""
Clean Start Script

This script clears both SQLite database and ChromaDB vector store
to start fresh data accumulation.
"""

import sys
import os
import sqlite3
import shutil
from pathlib import Path
import logging
from dotenv import load_dotenv

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv(os.path.join(project_root, ".env"))

from rss_analyzer.cache import DB_PATH
from rss_analyzer.vector_store import vector_store

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_start():
    """Reset both databases to start fresh"""
    print("🔄 Starting clean slate process...")

    # 1. Clear SQLite database
    print("\n🗑️  Clearing SQLite database...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get current count
        cursor.execute("SELECT COUNT(*) FROM article_scores")
        count = cursor.fetchone()[0]
        print(f"   Found {count} records in SQLite")

        # Drop and recreate the table to ensure clean schema
        cursor.execute("DROP TABLE IF EXISTS article_scores")

        # Recreate with new schema (title and url columns)
        cursor.execute("""
            CREATE TABLE article_scores (
                article_id TEXT PRIMARY KEY,
                score REAL,
                data TEXT,
                title TEXT,
                url TEXT,
                updated_at TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        print("   ✅ SQLite database cleared and recreated with new schema")
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

    # 3. Clear ChromaDB directory (in case there are persisted files)
    print("\n🗑️  Clearing ChromaDB persistent files...")
    try:
        chroma_dir = os.getenv("RSS_VECTOR_DB_DIR", os.path.join(os.getcwd(), "chroma_db"))
        if os.path.exists(chroma_dir):
            import shutil
            shutil.rmtree(chroma_dir)
            print("   ✅ ChromaDB directory cleared")
        else:
            print("   ℹ️  ChromaDB directory not found, no need to clear")
    except Exception as e:
        print(f"   ❌ Error clearing ChromaDB directory: {e}")
        return False

    print("\n🎉 Clean start completed successfully!")
    print("Both databases are now empty and ready for fresh data accumulation.")
    return True


def main():
    print("🚀 Clean Start Tool")
    print("="*50)

    # Show current status
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM article_scores")
        sqlite_count = cursor.fetchone()[0]
        conn.close()
    except:
        sqlite_count = 0

    try:
        vector_count = vector_store.get_article_count()
    except:
        vector_count = 0

    print(f"Current status:")
    print(f"  - SQLite records: {sqlite_count}")
    print(f"  - Vector store records: {vector_count}")
    print()

    confirm = input("⚠️  This will DELETE ALL DATA from both databases. Continue? (y/N): ")
    if confirm.lower() == 'y':
        success = clean_start()
        if success:
            print("\n✨ Both databases are now ready for fresh data accumulation!")
        else:
            print("\n❌ Clean start process failed.")
    else:
        print("   Clean start cancelled.")


if __name__ == "__main__":
    main()