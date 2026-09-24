"""
Feedly API 客户端模块
处理与 Feedly 服务的所有交互
"""

import logging
import time
from typing import Optional

import requests

from .feedly_auth import (
    FEEDLY_CONFIG_FILE,
    get_feedly_headers,
    get_feedly_proxy as _get_proxy,
    load_feedly_config,
    refresh_access_token,
    refresh_feedly_config,
    save_feedly_config,
)


logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MARK_READ_BATCH_SIZE",
    "FEEDLY_CONFIG_FILE",
    "feedly_fetch_unread",
    "feedly_get_categories",
    "feedly_get_subscriptions",
    "feedly_get_unread_counts",
    "feedly_mark_read",
    "get_feedly_headers",
    "load_feedly_config",
    "refresh_access_token",
    "refresh_feedly_config",
    "save_feedly_config",
]


def _calculate_backoff_delay(
    response: requests.Response,
    attempt: int,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> float:
    """Calculate delay for 429 rate limit backoff using Retry-After header or exponential backoff."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            val = float(retry_after)
            return min(max(val, 0.5), max_delay)
        except (ValueError, TypeError):
            pass
    return min(base_delay * (2 ** attempt), max_delay)


def _request_with_token_refresh(
    method: str,
    url: str,
    config: dict,
    max_rate_limit_retries: int = 3,
    base_backoff: float = 2.0,
    **kwargs,
) -> requests.Response:
    """
    Perform a Feedly request with:
    1. Automatic token refresh and single retry on 401 Unauthorized.
    2. Exponential backoff and Retry-After retry on 429 Too Many Requests.
    """
    request_func = getattr(requests, method.lower())
    kwargs["headers"] = get_feedly_headers(config["token"])
    kwargs.setdefault("proxies", _get_proxy())

    attempt = 0
    refreshed = False

    while True:
        response = request_func(url, **kwargs)

        if response.status_code == 401 and not refreshed:
            refreshed_config = refresh_feedly_config(config)
            if refreshed_config:
                refreshed = True
                config.update(refreshed_config)
                kwargs["headers"] = get_feedly_headers(refreshed_config["token"])
                continue

        if response.status_code == 429 and attempt < max_rate_limit_retries:
            delay = _calculate_backoff_delay(response, attempt, base_delay=base_backoff)
            logger.warning(
                "Feedly API rate limited (429). Retrying in %.1fs (attempt %d/%d)...",
                delay,
                attempt + 1,
                max_rate_limit_retries,
            )
            time.sleep(delay)
            attempt += 1
            continue

        return response


def feedly_fetch_unread(
    stream_id: Optional[str] = None, limit: Optional[int] = None
) -> list | None:
    """
    从 Feedly 获取未读文章

    Args:
        stream_id: Feedly 流 ID，默认为所有文章
        limit: 获取文章数量限制 (None 或 <=0 代表不设限，获取全量未读)

    Returns:
        文章列表，失败返回 None
    """
    config = load_feedly_config()
    if not config:
        logger.error("Feedly未配置，无法获取未读文章")
        return None

    user_id = config["user_id"]
    base_url = "https://cloud.feedly.com/v3"

    target_stream = stream_id or f"user/{user_id}/category/global.all"

    try:
        articles = []
        continuation = None
        has_limit = limit is not None and limit > 0

        while not has_limit or len(articles) < limit:
            # Calculate remaining needed, but cap at 1000 per request (Feedly API limit usually)
            if has_limit:
                remaining = limit - len(articles)
                batch_size = min(remaining, 1000)
            else:
                batch_size = 1000

            params = {
                "streamId": target_stream,
                "count": batch_size,
                "unreadOnly": "true",
            }
            if continuation:
                params["continuation"] = continuation

            response = _request_with_token_refresh(
                "GET",
                f"{base_url}/streams/contents",
                config,
                params=params,
            )

            if response.status_code == 401:
                logger.error("Feedly认证失败，请检查token")
                return None if not articles else articles
            if response.status_code != 200:
                logger.error(
                    f"Feedly API错误: {response.status_code} - {response.text}"
                )
                return None if not articles else articles

            data = response.json()

            if "items" in data:
                for entry in data["items"]:
                    article = {
                        "title": entry.get("title", "No Title"),
                        "link": entry.get("alternate", [{}])[0].get("href", "")
                        if entry.get("alternate")
                        else "",
                        "published": entry.get("published", 0),
                        "summary": entry.get("summary", {}).get("content", "")
                        or entry.get("content", {}).get("content", ""),
                        "id": entry.get("id", ""),
                        "origin": entry.get("origin", {}).get("title", ""),
                    }
                    articles.append(article)

            # Check for continuation token
            continuation = data.get("continuation")
            if not continuation:
                break

            if has_limit:
                logger.debug(f"Fetched {len(articles)}/{limit} articles... (Continuating)")
            else:
                logger.debug(f"Fetched {len(articles)} articles so far... (Continuating)")

        # Trim to exact limit if we over-fetched
        return articles if not has_limit else articles[:limit]
    except Exception as e:
        logger.error(f"获取Feedly未读文章异常: {str(e)}")
        import traceback
        import sys

        traceback.print_exc(file=sys.stderr)
        return None


DEFAULT_MARK_READ_BATCH_SIZE = 100


def feedly_mark_read(
    article_ids: list | str,
    batch_size: int = DEFAULT_MARK_READ_BATCH_SIZE,
) -> bool:
    """
    标记文章为已读

    Args:
        article_ids: 文章 ID 或 ID 列表
        batch_size: 每批提交给 Feedly markers API 的文章数量（默认 100，建议 ≤ 200 以防超时与限流）

    Returns:
        是否成功
    """
    config = load_feedly_config()
    if not config:
        logger.error("未找到 Feedly 配置，无法标记已读")
        return False

    base_url = "https://cloud.feedly.com/v3"

    if isinstance(article_ids, str):
        article_ids = [article_ids]

    if not article_ids:
        return True

    safe_batch_size = max(1, batch_size)

    try:
        all_success = True
        for i in range(0, len(article_ids), safe_batch_size):
            chunk = article_ids[i : i + safe_batch_size]
            data = {"action": "markAsRead", "type": "entries", "entryIds": chunk}
            response = _request_with_token_refresh(
                "POST",
                f"{base_url}/markers",
                config,
                json=data,
            )

            if response.status_code == 200:
                logger.info(f"成功标记 {len(chunk)} 篇文章为已读")
            else:
                logger.error(f"标记已读失败: {response.status_code} - {response.text}")
                all_success = False

        return all_success
    except Exception as e:
        logger.error(f"标记已读异常: {str(e)}")
        return False


def feedly_get_categories() -> list | None:
    """
    获取用户的所有分类
    GET /v3/categories
    """
    config = load_feedly_config()
    if not config:
        return None

    base_url = "https://cloud.feedly.com/v3"

    try:
        response = _request_with_token_refresh(
            "GET",
            f"{base_url}/categories",
            config,
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"获取分类失败: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"获取分类异常: {str(e)}")
        return None


def feedly_get_subscriptions() -> list | None:
    """
    获取用户的所有订阅源
    GET /v3/subscriptions
    """
    config = load_feedly_config()
    if not config:
        return None

    base_url = "https://cloud.feedly.com/v3"

    try:
        response = _request_with_token_refresh(
            "GET",
            f"{base_url}/subscriptions",
            config,
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"获取订阅失败: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"获取订阅异常: {str(e)}")
        return None


def feedly_get_unread_counts() -> dict | None:
    """
    获取未读计数
    GET /v3/markers/counts
    Returns:
        Dict with 'unreadcounts' list
    """
    config = load_feedly_config()
    if not config:
        return None

    base_url = "https://cloud.feedly.com/v3"

    try:
        response = _request_with_token_refresh(
            "GET",
            f"{base_url}/markers/counts",
            config,
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"获取未读计数失败: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"获取未读计数异常: {str(e)}")
        return None
