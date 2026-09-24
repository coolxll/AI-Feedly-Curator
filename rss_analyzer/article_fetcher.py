from __future__ import annotations

import concurrent.futures
import logging
import os
from typing import Callable

import requests

from .config import PROJ_CONFIG

logger = logging.getLogger(__name__)

__all__ = [
    "fetch_article_content",
    "fetch_articles_content_concurrently",
]


def fetch_articles_content_concurrently(
    urls: list[str],
    max_workers: int = 5,
    fetch_one: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """
    并发抓取多篇文章内容

    Args:
        urls: 文章 URL 列表
        max_workers: 并发抓取线程数（默认 5）
        fetch_one: 单篇抓取函数（默认为 fetch_article_content）

    Returns:
        字典映射：{url: content}
    """
    if not urls:
        return {}

    worker = fetch_one or fetch_article_content
    unique_urls = [u for u in dict.fromkeys(urls) if u]
    if not unique_urls:
        return {}

    actual_workers = max(1, min(max_workers, len(unique_urls)))
    results: dict[str, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
        future_to_url = {executor.submit(worker, url): url for url in unique_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as e:
                logger.warning("Error fetching %s concurrently: %s", url, e)
                results[url] = f"处理异常: {str(e)}"

    return results


def fetch_article_content(url: str) -> str:
    """
    获取文章内容 - 使用 trafilatura 增强提取能力

    Args:
        url: 文章 URL

    Returns:
        文章正文内容
    """
    # 特定域名跳过抓取
    if "weixin.sogou.com" in url:
        return "内容跳过: 微信链接通常无法直接抓取，仅基于标题摘要分析"

    try:
        # 尝试导入 trafilatura
        try:
            import trafilatura
        except ImportError:
            return "错误: 请先安装 trafilatura 库 (pip install trafilatura) 以获得更好的文章提取效果"

        # 配置代理 (优先使用环境变量，其次使用配置)
        proxy = (
            os.getenv("HTTP_PROXY")
            or os.getenv("HTTPS_PROXY")
            or PROJ_CONFIG.get("proxy")
        )
        proxies = {"http": proxy, "https": proxy} if proxy else None

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # 直接使用 requests 获取，确保代理生效
        try:
            response = requests.get(url, headers=headers, proxies=proxies, timeout=15)
            if response.status_code == 200:
                downloaded = response.content
            else:
                return f"获取失败: HTTP {response.status_code}"
        except Exception as req_err:
            return f"请求异常: {str(req_err)}"

        # 提取正文
        if downloaded:
            result = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False
            )
            if result:
                return result[:10000]  # 限制长度
            else:
                return "内容提取为空 (可能是纯JS渲染页面)"
        else:
            return "下载内容为空"

    except Exception as e:
        import traceback
        import sys

        traceback.print_exc(file=sys.stderr)
        return f"处理异常: {str(e)}"
