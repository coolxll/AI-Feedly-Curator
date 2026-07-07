"""
Feedly API 客户端模块
处理与 Feedly 服务的所有交互
"""

import os
import json
import logging
import time
import requests
from typing import Optional

from .config import PROJ_CONFIG


logger = logging.getLogger(__name__)

TOKEN_URL = "https://cloud.feedly.com/v3/auth/token"
WEB_CLIENT_ID = "feedly"
PKCE_CLIENT_ID = "feedlydev"
PKCE_CLIENT_SECRET = "feedlydev"


def _resolve_feedly_config_file() -> str:
    """Resolve the Feedly config file while preserving the old cwd default."""
    candidates = [
        os.getenv("FEEDLY_CONFIG_PATH"),
        os.path.join(os.getcwd(), "feedly_config.json"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "feedly_config.json"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return candidates[1]


FEEDLY_CONFIG_FILE = _resolve_feedly_config_file()


def load_feedly_config() -> dict | None:
    """加载 Feedly 配置"""
    if os.path.exists(FEEDLY_CONFIG_FILE):
        with open(FEEDLY_CONFIG_FILE, "r") as f:
            return json.load(f)
    return None


def save_feedly_config(config: dict) -> None:
    """保存 Feedly 配置"""
    with open(FEEDLY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_feedly_headers(token: str) -> dict:
    """获取 Feedly API 请求头"""
    return {"Authorization": f"OAuth {token}"}


def _get_proxy() -> dict | None:
    """获取代理配置"""
    proxy = (
        os.getenv("FEEDLY_PROXY_URL")
        or os.getenv("HTTP_PROXY")
        or os.getenv("HTTPS_PROXY")
        or PROJ_CONFIG.get("proxy")
    )
    if proxy and "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy} if proxy else None


def refresh_access_token(refresh_token: str) -> dict:
    """Refresh Feedly access_token using web-session first, then PKCE fallback."""
    proxy = _get_proxy()
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": WEB_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            proxies=proxy,
            timeout=15,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        logger.debug(
            "Feedly web-session token refresh failed; trying PKCE fallback",
            exc_info=True,
        )

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": PKCE_CLIENT_ID,
            "client_secret": PKCE_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        proxies=proxy,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def refresh_feedly_config(config: dict) -> dict | None:
    """Refresh token and persist the updated Feedly config."""
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        logger.error("Feedly token expired and no refresh_token is configured")
        return None

    try:
        token_data = refresh_access_token(refresh_token)
    except requests.RequestException as exc:
        logger.error("Feedly token refresh failed: %s", exc)
        return None

    config["token"] = token_data["access_token"]
    config["user_id"] = token_data.get("id", config.get("user_id", ""))
    config["refresh_token"] = token_data.get("refresh_token") or refresh_token
    expires_in = token_data.get("expires_in", 604800)
    config["token_expires_in"] = expires_in
    config["token_expires_at"] = int(time.time()) + expires_in
    save_feedly_config(config)
    logger.info("Feedly access_token refreshed successfully")
    return config


def _request_with_token_refresh(
    method: str, url: str, config: dict, **kwargs
) -> requests.Response:
    """Perform one Feedly request and retry once after refreshing on 401."""
    request_func = getattr(requests, method.lower())
    kwargs["headers"] = get_feedly_headers(config["token"])
    kwargs.setdefault("proxies", _get_proxy())
    response = request_func(url, **kwargs)
    if response.status_code != 401:
        return response

    refreshed = refresh_feedly_config(config)
    if not refreshed:
        return response

    kwargs["headers"] = get_feedly_headers(refreshed["token"])
    return request_func(url, **kwargs)


def feedly_fetch_unread(
    stream_id: Optional[str] = None, limit: int = 999
) -> list | None:
    """
    从 Feedly 获取未读文章

    Args:
        stream_id: Feedly 流 ID，默认为所有文章
        limit: 获取文章数量限制

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

        while len(articles) < limit:
            # Calculate remaining needed, but cap at 1000 per request (Feedly API limit usually)
            remaining = limit - len(articles)
            batch_size = min(remaining, 1000)

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

            logger.debug(f"Fetched {len(articles)}/{limit} articles... (Continuating)")

        # Trim to exact limit if we over-fetched (though unlikely with logic above)
        return articles[:limit]
    except Exception as e:
        logger.error(f"获取Feedly未读文章异常: {str(e)}")
        import traceback
        import sys

        traceback.print_exc(file=sys.stderr)
        return None


def feedly_mark_read(article_ids: list | str) -> bool:
    """
    标记文章为已读

    Args:
        article_ids: 文章 ID 或 ID 列表

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

    try:
        data = {"action": "markAsRead", "type": "entries", "entryIds": article_ids}
        response = _request_with_token_refresh(
            "POST",
            f"{base_url}/markers",
            config,
            json=data,
        )

        if response.status_code == 200:
            logger.info(f"成功标记 {len(article_ids)} 篇文章为已读")
            return True
        else:
            logger.error(f"标记已读失败: {response.status_code} - {response.text}")
            return False
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
