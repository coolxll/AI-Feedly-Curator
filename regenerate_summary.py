#!/usr/bin/env python3
"""
重新生成总体摘要
从 analyzed_articles.json 读取已分析的文章，重新生成总体摘要
"""
import os
from datetime import datetime

from rss_analyzer.config import setup_logging
from rss_analyzer.llm_analyzer import generate_overall_summary
from rss_analyzer.utils import load_articles


def generate_summary_from_articles(articles):
    """从已分析的文章生成并保存总体摘要"""
    # 创建输出目录
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    print("\n正在生成总体摘要...")
    overall_summary = generate_overall_summary(articles)

    # 生成带时间戳的文件名，按月份组织
    now = datetime.now()
    month_dir = now.strftime("%Y-%m")  # 例如: 2026-01
    output_dir = os.path.join("output", month_dir)
    os.makedirs(output_dir, exist_ok=True)

    timestamp = now.strftime("%Y%m%d_%H%M%S")
    summary_file = os.path.join(output_dir, f"summary_{timestamp}.md")

    # 同时保存到最新版本（在根 output 目录）
    latest_file = os.path.join("output", "summary_latest.md")

    print("\n正在保存摘要...")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(overall_summary)

    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write(overall_summary)

    print("✓ 总体摘要已保存到:")
    print(f"  - {summary_file}")
    print(f"  - {latest_file}")

    return summary_file, latest_file


def main():
    """重新生成总体摘要"""
    setup_logging()

    print("正在加载已分析的文章...")
    articles = load_articles('analyzed_articles.json')
    print(f"已加载 {len(articles)} 篇文章")

    generate_summary_from_articles(articles)


if __name__ == "__main__":
    main()
