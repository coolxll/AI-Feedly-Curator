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
from rss_analyzer.llm_analyzer import analyze_article_with_llm, analyze_articles_with_llm_batch
from rss_analyzer.utils import is_newsflash
from rss_analyzer.cache import get_cached_score, save_cached_score

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """过滤结果"""
    matched: list      # 匹配的文章（将被标记为已读）
    remaining: list    # 剩余文章（未匹配）
    label: str         # 标签（用于日志）


# 36kr Feed 源 ID
FEED_ID_36KR = "feed/http://www.36kr.com/feed"


# ============================================================================
# Core Functions
# ============================================================================

def fetch_articles(limit: int, stream_id: str = None) -> list:
    """获取 Feedly 未读文章"""
    source_label = "36kr源" if stream_id == FEED_ID_36KR else "所有未读"
    logger.info(f"📥 从 [{source_label}] 获取未读文章 (limit={limit})...")
    
    articles = feedly_fetch_unread(stream_id=stream_id, limit=limit) or []
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
    # 既然已经指定了源，可能大部分都是快讯，但为了保险起见，还是保留 is_newsflash 检查
    # 或者如果 36kr 源里包含非快讯的普通文章，这个检查就是必要的
    matched = [a for a in articles if is_newsflash(a)]
    remaining = [a for a in articles if not is_newsflash(a)]
    logger.info(f"🗞️ 快讯: {len(matched)}/{len(articles)}")
    return FilterResult(matched, remaining, "快讯")


def low_score_filter(articles: list, threshold: float = 3.0, dry_run: bool = False) -> FilterResult:
    """低分文章过滤器，调用 LLM 对文章进行评分并根据阈值过滤"""
    matched, remaining = [], []
    batch_scoring = PROJ_CONFIG.get("batch_scoring", False)
    batch_size = max(1, int(PROJ_CONFIG.get("batch_size", 1)))
    batch_queue = []

    for i, article in enumerate(articles, 1):
        title = article.get('title', '')[:50]
        prefix = f"[{i}/{len(articles)}]"
        article_id = article.get('id')

        # 1. Check Cache
        cached = get_cached_score(article_id)
        if cached:
            score = cached['score']
            logger.info(f"{prefix} ♻️ 使用缓存评分: {title}")
            _handle_scored_article(
                article,
                score,
                prefix,
                threshold,
                dry_run,
                matched,
                remaining
            )
            continue

        logger.info(f"{prefix} 评分中: {title}...")

        if batch_scoring:
            batch_queue.append({
                "article": article,
                "prefix": prefix,
                "payload": _prepare_article_scoring(article)
            })
            if len(batch_queue) >= batch_size:
                batch_payload = [item["payload"] for item in batch_queue]
                batch_results = analyze_articles_with_llm_batch(batch_payload)
                for item, analysis in zip(batch_queue, batch_results):
                    score = analysis.get("score", 0.0)
                    # Save to Cache
                    save_cached_score(item["article"].get('id'), score, analysis)

                    _handle_scored_article(
                        item["article"],
                        score,
                        item["prefix"],
                        threshold,
                        dry_run,
                        matched,
                        remaining
                    )
                batch_queue = []
        else:
            score, analysis = _score_article(article)
            # Save to Cache (if valid)
            if score >= 0:
                save_cached_score(article_id, score, analysis)

            _handle_scored_article(
                article,
                score,
                prefix,
                threshold,
                dry_run,
                matched,
                remaining
            )

    if batch_scoring and batch_queue:
        batch_payload = [item["payload"] for item in batch_queue]
        batch_results = analyze_articles_with_llm_batch(batch_payload)
        for item, analysis in zip(batch_queue, batch_results):
            score = analysis.get("score", 0.0)
            # Save to Cache
            save_cached_score(item["article"].get('id'), score, analysis)

            _handle_scored_article(
                item["article"],
                score,
                item["prefix"],
                threshold,
                dry_run,
                matched,
                remaining
            )
        batch_queue = []

    logger.info(f"📊 过滤结果: {len(matched)} 篇过滤, {len(remaining)} 篇保留")
    return FilterResult(matched, remaining, "低分")


def _score_article(article: dict) -> tuple[float, dict]:
    """对文章进行评分，返回 (score, analysis_data)"""
    payload = _prepare_article_scoring(article)

    # 调用配置的分析模型进行评分
    try:
        result = analyze_article_with_llm(
            payload.get("title", ""),
            payload.get("summary", ""),
            payload.get("content", "")
        )
        return result.get('score', 0.0), result
    except Exception as e:
        logger.debug(f"评分出错: {e}")
        return -1.0, {}


def _prepare_article_scoring(article: dict) -> dict:
    """准备文章评分所需的 Payload"""
    title, summary = article.get('title', ''), article.get('summary', '')
    content = article.get('content', '')

    if not (content and len(content) > 200):
        content = summary if len(summary) > 500 else _fetch_content(article) or summary

    return {
        "title": title,
        "summary": summary,
        "content": content
    }


def _handle_scored_article(article: dict, score: float, prefix: str, threshold: float, dry_run: bool,
                           matched: list, remaining: list) -> None:
    """处理评分后的文章，决定是标记已读还是保留"""
    
    title_str = article.get('title', 'Unknown Title')
    if score < 0:
        logger.info(f"{prefix} 结果: 跳过 (评分失败)")
        remaining.append(article)
    elif score <= threshold:
        article_id = article.get('id')
        if article_id and not dry_run:
            feedly_mark_read([article_id])
            logger.info(f"{prefix} 结果: ❌标题: {title_str}")
            logger.info(f"{prefix} 结果: {score:.1f} 分 (低于阈值，已标记已读)")
        else:
            logger.info(f"{prefix} 结果: ❌标题: {title_str}")
            logger.info(f"{prefix} 结果: {score:.1f} 分 (低于阈值，[DRY RUN] 跳过标记)")
        matched.append({**article, '_score': score})
    else:
        logger.info(f"{prefix} 结果: ✅标题: {title_str}")
        logger.info(f"{prefix} 结果: {score:.1f} 分 (保留)")
        remaining.append(article)


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
    parser.add_argument('--limit', '-l', type=int, default=500, help='获取文章数量')
    parser.add_argument('--threshold', '-t', type=float, default=3.0, help='低分阈值')
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
    
    # 策略路由
    if args.cmd == 'newsflash':
        # 专门从 36kr 源获取
        articles = fetch_articles(args.limit, stream_id=FEED_ID_36KR)
        filters = [newsflash_filter]
    elif args.cmd == 'low-score':
        # 从全局获取
        articles = fetch_articles(args.limit)
        filters = [lambda a: low_score_filter(a, args.threshold, args.dry_run)]
    else:  # all
        # 全量模式逻辑：
        # 1. 先跑一遍快讯过滤（针对性清理）- 可选，或者直接由全局处理覆盖
        # 2. 再跑全局
        # 为了简单且符合"all"的语义（处理所有未读），这里我们只做一次全局 fetch
        # 如果用户希望分开跑，应该分别调用 newsflash 和 low-score
        
        # 修正：根据用户意图，可能希望 all 也能享受到针对性过滤的好处？
        # 但"all"通常意味着处理所有来源。如果只 fetch 36kr，就漏了别的。
        # 如果 fetch global，也包含 36kr。
        # 所以 all 模式维持原样（fetch global），但应用所有过滤器。
        
        articles = fetch_articles(args.limit)
        filters = [newsflash_filter, lambda a: low_score_filter(a, args.threshold, args.dry_run)]

    if not articles:
        return 0
    
    return run_filters(articles, filters, args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
