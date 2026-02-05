#!/usr/bin/env python3
"""
Vector Store Cleanup Script

This script provides various cleanup operations for the ChromaDB vector store:
1. Clear all data
2. Remove specific articles by ID
3. Remove invalid entries
4. Display statistics
"""

import argparse
import os
import sys
from typing import List
from dotenv import load_dotenv

# Add project root to path FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv(os.path.join(project_root, ".env"))

# Need to set up path before importing local modules
from rss_analyzer.vector_store import vector_store  # noqa: E402


def display_stats():
    """Display current statistics about the vector store"""
    count = vector_store.get_article_count()
    print("\n📊 Current vector store statistics:")
    print(f"   Total articles: {count}")

    if count > 0:
        all_ids = vector_store.get_all_article_ids()
        print(f"   Sample article IDs: {all_ids[:5]}{'...' if len(all_ids) > 5 else ''}")


def clear_all_data():
    """Clear all data from the vector store"""
    print("\n🗑️  Clearing all data from vector store...")

    count_before = vector_store.get_article_count()
    if count_before == 0:
        print("   Vector store is already empty!")
        return

    success = vector_store.clear_collection()
    if success:
        count_after = vector_store.get_article_count()
        print(f"   ✅ Cleared all {count_before} articles. Now has {count_after} articles.")
    else:
        print("   ❌ Failed to clear vector store")


def remove_by_ids(article_ids: List[str]):
    """Remove specific articles by their IDs"""
    print(f"\n🗑️  Removing {len(article_ids)} specific articles...")

    for article_id in article_ids:
        print(f"   - Processing: {article_id[:20]}...")

    success = vector_store.delete_articles(article_ids)
    if success:
        print(f"   ✅ Successfully removed {len(article_ids)} articles")
    else:
        print("   ❌ Failed to remove articles")


def cleanup_invalid():
    """Clean up invalid entries from the vector store"""
    print("\n🧹 Cleaning up invalid entries...")

    count_before = vector_store.get_article_count()
    removed_count = vector_store.cleanup_invalid_entries()

    count_after = vector_store.get_article_count()
    print(f"   ✅ Removed {removed_count} invalid entries")
    print(f"   📊 Count before: {count_before}, after: {count_after}")


def main():
    parser = argparse.ArgumentParser(description="Vector Store Cleanup Utility")
    parser.add_argument("--stats", action="store_true", help="Show current statistics")
    parser.add_argument("--clear-all", action="store_true", help="Clear all data from vector store")
    parser.add_argument("--remove-ids", nargs="+", help="Remove specific article IDs")
    parser.add_argument("--cleanup-invalid", action="store_true", help="Remove invalid entries")

    args = parser.parse_args()

    # If no arguments provided, show stats by default
    if not any([args.stats, args.clear_all, args.remove_ids, args.cleanup_invalid]):
        args.stats = True

    print("🔄 Connecting to vector store...")

    try:
        # Verify connection
        initial_count = vector_store.get_article_count()
        print(f"✅ Connected to vector store. Current count: {initial_count}")
    except Exception as e:
        print(f"❌ Failed to connect to vector store: {e}")
        return

    if args.stats:
        display_stats()

    if args.clear_all:
        confirm = input("\n⚠️  This will remove ALL data from the vector store. Continue? (y/N): ")
        if confirm.lower() == 'y':
            clear_all_data()
        else:
            print("   Operation cancelled.")

    if args.remove_ids:
        print(f"Removing {len(args.remove_ids)} specific articles...")
        for aid in args.remove_ids:
            print(f"  - {aid}")
        confirm = input("\n⚠️  Continue with removal? (y/N): ")
        if confirm.lower() == 'y':
            remove_by_ids(args.remove_ids)
        else:
            print("   Operation cancelled.")

    if args.cleanup_invalid:
        cleanup_invalid()

    # Show final stats if any operations were performed
    if any([args.clear_all, args.remove_ids, args.cleanup_invalid]):
        print("\n📈 Final statistics:")
        display_stats()


if __name__ == "__main__":
    main()