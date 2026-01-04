#!/usr/bin/env python3
"""
36kr 快讯一键标记已读脚本

用于将 36kr 的 newsflash（快讯）批量标记为已读，
避免在主流程中处理大量低价值的快讯内容。
"""

import argparse
import logging
import sys

from rss_analyzer.feedly_client import (
    load_feedly_config,
    feedly_fetch_unread,
    feedly_mark_read,
    get_feedly_headers,
    _get_proxy
)
import requests

# 36kr Feed URL (从 rss.opml 中获取)
FEED_36KR_URL = "http://www.36kr.com/feed"

# Feedly stream ID 格式: feed/<feed_url>
STREAM_ID_36KR = f"feed/{FEED_36KR_URL}"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_feed_subscriptions() -> list:
    """获取所有订阅的 feed 列表"""
    config = load_feedly_config()
    if not config:
        logger.error("未找到 Feedly 配置")
        return []
    
    token = config['token']
    base_url = "https://cloud.feedly.com/v3"
    
    try:
        response = requests.get(
            f"{base_url}/subscriptions",
            headers=get_feedly_headers(token),
            proxies=_get_proxy()
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"获取订阅列表失败: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"获取订阅列表异常: {e}")
        return []


def find_36kr_feed_id() -> str | None:
    """从订阅列表中查找 36kr 的 feed ID"""
    subscriptions = get_feed_subscriptions()
    
    for sub in subscriptions:
        feed_id = sub.get('id', '')
        title = sub.get('title', '')
        
        # 匹配 36kr 或 36氪
        if '36kr' in feed_id.lower() or '36氪' in title:
            logger.info(f"找到 36kr feed: {title} ({feed_id})")
            return feed_id
    
    logger.warning("未在订阅中找到 36kr feed")
    return None


def fetch_36kr_unread(feed_id: str, limit: int = 500) -> list:
    """获取 36kr 的未读文章"""
    articles = feedly_fetch_unread(stream_id=feed_id, limit=limit)
    if articles is None:
        return []
    return articles


def mark_all_as_read(articles: list, dry_run: bool = False) -> bool:
    """将所有文章标记为已读"""
    if not articles:
        logger.info("没有未读文章需要标记")
        return True
    
    article_ids = [a['id'] for a in articles if a.get('id')]
    
    if dry_run:
        logger.info(f"[DRY RUN] 将标记 {len(article_ids)} 篇文章为已读")
        for article in articles[:10]:
            logger.info(f"  - {article.get('title', 'No Title')[:50]}")
        if len(articles) > 10:
            logger.info(f"  ... 还有 {len(articles) - 10} 篇")
        return True
    
    # Feedly API 限制每次最多标记 1000 条
    batch_size = 500
    success = True
    
    for i in range(0, len(article_ids), batch_size):
        batch = article_ids[i:i + batch_size]
        if not feedly_mark_read(batch):
            logger.error(f"标记第 {i+1}-{i+len(batch)} 篇文章失败")
            success = False
    
    return success


def filter_newsflash(articles: list) -> list:
    """
    过滤出快讯类文章
    
    36kr 快讯特征：
    - 标题通常包含"快讯"或以特定格式开头
    - 内容通常较短
    - origin 可能包含 newsflash 相关标识
    """
    newsflash = []
    for article in articles:
        title = article.get('title', '')
        summary = article.get('summary', '')
        
        # 快讯特征: 标题短、内容短
        is_short_title = len(title) < 80
        is_short_content = len(summary) < 500
        
        # 可能的快讯关键词
        has_flash_keyword = any(kw in title for kw in ['快讯', '7x24', '要闻'])
        
        # 如果符合快讯特征，加入列表
        if is_short_content and (is_short_title or has_flash_keyword):
            newsflash.append(article)
    
    return newsflash


def main():
    parser = argparse.ArgumentParser(
        description='36kr 快讯一键标记已读'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='仅显示将要标记的文章，不实际执行'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='标记所有 36kr 文章为已读（默认只标记快讯类）'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=500,
        help='获取的最大文章数量（默认 500）'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试日志'
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 查找 36kr feed
    feed_id = find_36kr_feed_id()
    if not feed_id:
        # 尝试使用默认 stream ID
        feed_id = STREAM_ID_36KR
        logger.info(f"使用默认 feed ID: {feed_id}")
    
    # 获取未读文章
    logger.info(f"正在获取 36kr 未读文章 (limit={args.limit})...")
    articles = fetch_36kr_unread(feed_id, limit=args.limit)
    
    if not articles:
        logger.info("没有未读的 36kr 文章")
        return 0
    
    logger.info(f"共获取 {len(articles)} 篇未读文章")
    
    # 过滤或全部处理
    if args.all:
        target_articles = articles
        logger.info("将标记所有文章为已读")
    else:
        target_articles = filter_newsflash(articles)
        logger.info(f"过滤出 {len(target_articles)} 篇快讯类文章")
    
    if not target_articles:
        logger.info("没有符合条件的文章需要标记")
        return 0
    
    # 显示将要处理的文章
    logger.info("将要标记为已读的文章:")
    for article in target_articles[:5]:
        title = article.get('title', 'No Title')
        logger.info(f"  - {title[:60]}{'...' if len(title) > 60 else ''}")
    if len(target_articles) > 5:
        logger.info(f"  ... 还有 {len(target_articles) - 5} 篇")
    
    # 执行标记
    if mark_all_as_read(target_articles, dry_run=args.dry_run):
        if not args.dry_run:
            logger.info(f"✅ 成功标记 {len(target_articles)} 篇文章为已读")
        return 0
    else:
        logger.error("❌ 标记失败")
        return 1


if __name__ == '__main__':
    sys.exit(main())
