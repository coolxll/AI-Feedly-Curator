#!/usr/bin/env python3
"""
重新生成总体摘要
从 analyzed_articles.json 读取已分析的文章，重新生成总体摘要
"""
from rss_analyzer.config import setup_logging
from rss_analyzer.llm_analyzer import generate_overall_summary
from rss_analyzer.utils import load_articles


def main():
    """重新生成总体摘要"""
    setup_logging()
    
    print("正在加载已分析的文章...")
    articles = load_articles('analyzed_articles.json')
    print(f"已加载 {len(articles)} 篇文章")
    
    print("\n正在生成总体摘要...")
    overall_summary = generate_overall_summary(articles)
    
    print("\n正在保存摘要...")
    with open('articles_summary.md', 'w', encoding='utf-8') as f:
        f.write(overall_summary)
    
    print("✓ 总体摘要已重新生成并保存到 articles_summary.md")


if __name__ == "__main__":
    main()
