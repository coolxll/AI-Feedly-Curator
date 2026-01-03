#!/usr/bin/env python3
"""
Verify Scoring Script
单独测试文章评分功能的脚本
支持通过 local file 抓取或直接输入文本进行评分
"""
import argparse
import sys
import json
import logging

# Ensure parent directory is in path
sys.path.append('.')

from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.scoring import score_article
from rss_analyzer.config import setup_logging

def process_article(article, index):
    title = article.get('title', 'No Title')
    content = article.get('content', '')
    summary = article.get('summary', '')
    
    # Check content validity
    # Check content validity & Fetch if needed
    if not content or len(content) < 200:
        if summary and len(summary) > 500:
            # Fallback to summary if it's long enough
            content = summary
        else:
            # Try fetching from URL
            link = article.get('link') or article.get('originId') # Feedly sometimes puts link in originId or id
            if link and link.startswith('http'):
                print(f"🌍 Fetching content for [{index}] from: {link}")
                try:
                    fetched = fetch_article_content(link)
                    if fetched and len(fetched) > 200:
                        content = fetched
                        print(f"✅ Fetched {len(content)} chars.")
                    else:
                         print(f"⚠️ Fetch failed or too short, falling back to summary.")
                         content = summary if summary else ""
                except Exception as e:
                    print(f"⚠️ Fetch error: {e}")
                    content = summary if summary else ""
            else:
                 content = summary if summary else ""

    if not content or len(content) < 50:
         print(f"❌ Article [{index}] skipped: Content too short ({len(content)} chars) & Fetch failed.")
         return

    print(f"\n" + "="*60)
    print(f"🤖 正在处理 [{index}]: {title}")
    
    # 评分
    try:
        result = score_article(title, summary, content)
    except Exception as e:
        print(f"❌ 评分失败: {e}")
        return

    emoji = "😐"
    if result.get('overall_score', 0) >= 3.8: emoji = "🔥"
    if result.get('overall_score', 0) < 3.0: emoji = "👎"
    
    print("-" * 60)
    print(f"� 摘要: {summary[:100]}..." if summary else "📝 摘要: (无)")
    print("-" * 60)
    print(f"📊 总分: {result.get('overall_score')}/5.0 {emoji}")
    print(f"⚖️ 结论: {result.get('verdict')}")
    print("-" * 30)
    print("评分维度:")
    print(f"  相关性: {result.get('relevance_score')} | 信息量: {result.get('informativeness_accuracy_score')} | 深度: {result.get('depth_opinion_score')} | 可读性: {result.get('readability_score')} | 原创性: {result.get('non_redundancy_score')}")
    
    if result.get('red_flags'):
        print(f"🚩 负面特征: {result.get('red_flags')}")
        
    print("-" * 30)
    print(f"🧠 分析 (CoT): {result.get('reason') or result.get('comment')}")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Test RSS Opml Scoring Logic (Local JSON Mode)")
    parser.add_argument("--input", default="unread_news.json", help="Path to unread articles JSON")
    parser.add_argument("--index", type=int, help="Index of specific article to score (optional)")
    parser.add_argument("--limit", type=int, help="Limit number of articles to process (optional)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    setup_logging(args.debug)
    
    # Load articles
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            articles = json.load(f)
    except Exception as e:
        print(f"❌ Error loading file {args.input}: {e}")
        sys.exit(1)
        
    if not articles:
        print("❌ No articles found.")
        sys.exit(1)
        
    if args.index is not None:
        # Process single article
        if args.index < 0 or args.index >= len(articles):
            print(f"❌ Index {args.index} out of range (0-{len(articles)-1})")
            sys.exit(1)
        process_article(articles[args.index], args.index)
    else:
        # Process multiple/all articles
        count = len(articles)
        if args.limit:
            count = min(count, args.limit)
            
        print(f"🚀 Batch processing {count} articles...")
        print(f"File: {args.input}")
        
        for i, article in enumerate(articles):
            if args.limit and i >= args.limit:
                break
            process_article(article, i)

if __name__ == "__main__":
    main()
