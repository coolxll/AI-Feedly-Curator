#!/usr/bin/env python3
"""
Test script to verify the semantic search filtering functionality with actual search
"""
import os
import sys

# Add parent directory to path to import modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PARENT_DIR))

from rss_analyzer.vector_store import vector_store

def test_search_functionality():
    print("🔍 Testing semantic search with score filtering...")

    # Check the database content
    count = vector_store.get_article_count()
    print(f"\n📊 Vector store contains {count} articles")

    # Test search without filtering
    print("\n1. Testing search without score filter:")
    try:
        results_no_filter = vector_store.search_similar("技术", limit=5)
        print(f"   Found {len(results_no_filter)} results:")
        for i, result in enumerate(results_no_filter):
            score = result["metadata"].get("score", "N/A")
            title = result["metadata"].get("title", "No title")[:50] + "..."
            print(f"   {i+1}. Score: {score}, Title: {title}")
    except Exception as e:
        print(f"   Error during search without filter: {e}")

    # Test search with minimum score filter
    print("\n2. Testing search with minimum score filter (score >= 3.0):")
    try:
        results_with_filter = vector_store.search_similar("技术", limit=5, min_score=3.0)
        print(f"   Found {len(results_with_filter)} results after filtering:")
        for i, result in enumerate(results_with_filter):
            score = result["metadata"].get("score", "N/A")
            title = result["metadata"].get("title", "No title")[:50] + "..."
            print(f"   {i+1}. Score: {score}, Title: {title}")

        # Verify that all results meet the filter criteria
        all_meet_criteria = all(result["metadata"].get("score", 0) >= 3.0 for result in results_with_filter)
        print(f"   ✅ All results meet criteria (score >= 3.0): {all_meet_criteria}")

    except Exception as e:
        print(f"   Error during search with filter: {e}")

    # Test with even higher threshold
    print("\n3. Testing search with high score filter (score >= 4.0):")
    try:
        results_high_filter = vector_store.search_similar("科技", limit=5, min_score=4.0)
        print(f"   Found {len(results_high_filter)} results after high filtering:")
        for i, result in enumerate(results_high_filter):
            score = result["metadata"].get("score", "N/A")
            title = result["metadata"].get("title", "No title")[:50] + "..."
            print(f"   {i+1}. Score: {score}, Title: {title}")

        # Verify that all results meet the high filter criteria
        all_meet_high_criteria = all(result["metadata"].get("score", 0) >= 4.0 for result in results_high_filter)
        print(f"   ✅ All results meet criteria (score >= 4.0): {all_meet_high_criteria}")

    except Exception as e:
        print(f"   Error during high score search: {e}")

    # Compare the results
    print(f"\n📈 Filtering effectiveness:")
    print(f"   Without filter: {len(results_no_filter) if 'results_no_filter' in locals() else 0} results")
    print(f"   With score >= 3.0: {len(results_with_filter) if 'results_with_filter' in locals() else 0} results")
    print(f"   With score >= 4.0: {len(results_high_filter) if 'results_high_filter' in locals() else 0} results")

    print(f"\n🎉 Semantic search filtering test completed!")

if __name__ == "__main__":
    test_search_functionality()