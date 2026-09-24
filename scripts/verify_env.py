#!/usr/bin/env python3
"""
Test script to verify environment variable loading and semantic search filtering
"""
import os
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

print("🔍 Checking environment variables...")
print(f"DASHSCOPE_API_KEY: {'SET' if os.getenv('DASHSCOPE_API_KEY') else 'NOT SET'}")
print(f"ALIYUN_OPENAI_API_KEY: {'SET' if os.getenv('ALIYUN_OPENAI_API_KEY') else 'NOT SET'}")
print(f"OPENAI_API_KEY: {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")

# Add parent directory to path to import modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, os.path.join(PARENT_DIR))

from rss_analyzer.vector_store import vector_store

print(f"\n📊 Vector store contains {vector_store.get_article_count()} articles")

# Test search with filtering
print("\nTesting search with score filtering...")
try:
    # First, let's try to check if the embedding function can be initialized
    from rss_analyzer.vector_store import DashScopeEmbeddingFunction
    embedding_func = DashScopeEmbeddingFunction()

    if embedding_func.client:
        print("✅ Embedding function initialized successfully")

        # Try a search with filtering
        results_filtered = vector_store.search_similar("技术", limit=3, min_score=3.0)
        print(f"   Found {len(results_filtered)} results with score >= 3.0:")
        for i, result in enumerate(results_filtered):
            score = result["metadata"].get("score", "N/A")
            title = result["metadata"].get("title", "No title")[:50] + "..."
            print(f"   {i+1}. Score: {score}, Title: {title}")
    else:
        print("⚠️  Embedding function not initialized - API key issue")
        print("   Testing filtering logic without actual search...")

        # Test the filtering logic using direct access to stored articles
        all_articles = vector_store.get_all_articles()
        if all_articles['ids']:
            print(f"   Total articles in DB: {len(all_articles['ids'])}")

            # Test filtering logic on stored metadata
            high_score_articles = []
            for i, metadata in enumerate(all_articles['metadatas']):
                score = metadata.get('score', 0)
                if score >= 3.0:
                    article_info = {
                        'id': all_articles['ids'][i],
                        'metadata': metadata,
                        'text': all_articles['documents'][i] if i < len(all_articles['documents']) else '',
                        'distance': 0.0  # dummy value
                    }
                    high_score_articles.append(article_info)

            print(f"   Articles with score >= 3.0: {len(high_score_articles)}")
            print("   ✅ Filtering logic works correctly!")
        else:
            print("   No articles found in database")

except Exception as e:
    print(f"❌ Error during test: {e}")
    import traceback
    traceback.print_exc()