#!/usr/bin/env python3
"""
Feedly 文章过滤器

统一的文章过滤工具，支持多种过滤模式：
- newsflash: 过滤 36kr 快讯
- low-score: 过滤低分文章
- all: 依次执行所有过滤

使用方法：
    python feedly_filter.py newsflash [--limit 500] [--dry-run]
    python feedly_filter.py low-score [--limit 100] [--threshold 2.5] [--dry-run]
    python feedly_filter.py all [--limit 200] [--threshold 2.5] [--dry-run]
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Callable

from rss_analyzer.config import PROJ_CONFIG, setup_logging
from rss_analyzer.feedly_client import feedly_fetch_unread, feedly_mark_read
from rss_analyzer.article_fetcher import fetch_article_content
from rss_analyzer.llm_analyzer import analyze_article_with_llm
from rss_analyzer.utils import is_newsflash

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """过滤结果"""
    matched: list      # 匹配的文章（将被标记为已读）
    remaining: list    # 剩余文章（未匹配）
    label: str         # 标签（用于日志）


# ============================================================================
# Core Functions
# ============================================================================

def fetch_articles(limit: int) -> list:
    """获取 Feedly 未读文章"""
    logger.info(f"📥 获取未读文章 (limit={limit})...")
    articles = feedly_fetch_unread(limit=limit) or []
    logger.info(f"✅ 获取到 {len(articles)} 篇")
    return articles


def mark_as_read(articles: list, label: str, dry_run: bool) -> bool:
    """标记文章为已读"""
    if not articles:
        return True
    
    ids = [a['id'] for a in articles if a.get('id')]
    
    if dry_run:
        logger.info(f"[DRY RUN] 将标记 {len(ids)} 篇{label}文章:")
        for a in articles[:5]:
            score = a.get('_score')
            prefix = f"[{score:.1f}] " if score else ""
            logger.info(f"  - {prefix}{a.get('title', '')[:50]}")
        if len(articles) > 5:
            logger.info(f"  ... 还有 {len(articles) - 5} 篇")
        return True
    
    for i in range(0, len(ids), 500):
        if not feedly_mark_read(ids[i:i+500]):
            logger.error(f"标记失败: {i+1}-{i+500}")
            return False
    
    logger.info(f"✅ 已标记 {len(ids)} 篇{label}文章")
    return True


def run_filters(articles: list, filters: list[Callable], dry_run: bool) -> int:
    """依次运行多个过滤器"""
    remaining = articles
    total_matched = 0
    
    for filter_func in filters:
        if not remaining:
            break
        result = filter_func(remaining)
        mark_as_read(result.matched, result.label, dry_run)
        total_matched += len(result.matched)
        remaining = result.remaining
    
    logger.info(f"📊 总计过滤: {total_matched}/{len(articles)}")
    return 0


# ============================================================================
# Filters
# ============================================================================

def newsflash_filter(articles: list) -> FilterResult:
    """快讯过滤器"""
    matched = [a for a in articles if is_newsflash(a)]
    remaining = [a for a in articles if not is_newsflash(a)]
    logger.info(f"🗞️ 快讯: {len(matched)}/{len(articles)}")
    return FilterResult(matched, remaining, "快讯")


def low_score_filter(articles: list, threshold: float = 2.5, dry_run: bool = False) -> FilterResult:
    """低分过滤器（假设已预先过滤快讯），边评分边标记"""
    matched, remaining = [], []
    
    for i, article in enumerate(articles, 1):
        title = article.get('title', '')[:50]
        prefix = f"[{i}/{len(articles)}]"
        
        logger.info(f"{prefix} 评分中: {title}...")
        score = _score_article(article)
        
        if score < 0:
            logger.info(f"{prefix} 结果: ⚠️ 评分失败 → 保留")
            remaining.append(article)
        elif score <= threshold:
            # 立即标记为已读
            article_id = article.get('id')
            if article_id and not dry_run:
                feedly_mark_read([article_id])
                logger.info(f"{prefix} 结果: {score:.1f} 🚫 → 已标记已读 ✓")
            else:
                logger.info(f"{prefix} 结果: {score:.1f} 🚫 → [DRY RUN] 将标记已读")
            matched.append({**article, '_score': score})
        else:
            logger.info(f"{prefix} 结果: {score:.1f} ✅ → 保留")
            remaining.append(article)
    
    logger.info(f"🤖 低分过滤完成: {len(matched)} 篇已标记, {len(remaining)} 篇保留")
    return FilterResult(matched, remaining, "低分")


def _score_article(article: dict) -> float:
    """评分单篇文章，失败返回 -1"""
    title, summary = article.get('title', ''), article.get('summary', '')
    content = article.get('content', '')
    
    if not (content and len(content) > 200):
        content = summary if len(summary) > 500 else _fetch_content(article) or summary
    
    # 即使内容较短也尝试评分，让 LLM 判断
    try:
        return analyze_article_with_llm(title, summary, content).get('score', 0.0)
    except Exception as e:
        logger.debug(f"评分异常: {e}")
        return -1.0


def _fetch_content(article: dict) -> str:
    """抓取文章内容"""
    link = article.get('canonicalUrl') or article.get('alternate', [{}])[0].get('href', '')
    return fetch_article_content(link) if link else ""


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Feedly 文章过滤器')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--limit', '-l', type=int, default=200, help='获取文章数量')
    parser.add_argument('--threshold', '-t', type=float, default=2.5, help='低分阈值')
    parser.add_argument('--dry-run', '-n', action='store_true', help='模拟模式')
    
    sub = parser.add_subparsers(dest='cmd')
    sub.add_parser('newsflash', help='过滤快讯')
    sub.add_parser('low-score', help='过滤低分')
    sub.add_parser('all', help='全量过滤')
    
    args = parser.parse_args()
    
    if args.debug:
        setup_logging(True)
    
    # 默认使用 all 命令
    if not args.cmd:
        args.cmd = 'all'
    
    articles = fetch_articles(args.limit)
    if not articles:
        return 0
    
    # 根据命令选择过滤器
    if args.cmd == 'newsflash':
        filters = [newsflash_filter]
    elif args.cmd == 'low-score':
        filters = [lambda a: low_score_filter(a, args.threshold, args.dry_run)]
    else:  # all
        filters = [newsflash_filter, lambda a: low_score_filter(a, args.threshold, args.dry_run)]
    
    return run_filters(articles, filters, args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
