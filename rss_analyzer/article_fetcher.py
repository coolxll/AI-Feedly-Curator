from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import os
import socket
from collections.abc import Mapping
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from .config import PROJ_CONFIG, get_max_content_chars

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_CONTENT_TYPE_PREFIXES = ("audio/", "video/", "image/")
_BLOCKED_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
    }
)

__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
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


def _truncate_content(content: str, url: str) -> str:
    """Apply the configurable content-length cap, warning when it bites.

    Truncation is a token-cost trade-off, not a silent detail: dropping the
    tail of a long-form article changes what the LLM can score and summarize.
    Log loudly so the loss is visible instead of being mistaken for the
    article's real length.
    """
    limit = get_max_content_chars()
    if limit is None or limit <= 0 or len(content) <= limit:
        return content

    dropped = len(content) - limit
    logger.warning(
        "Article content truncated: kept %d/%d chars (dropped %d, %.0f%%) for %s. "
        "Raise RSS_MAX_CONTENT_CHARS to keep more.",
        limit,
        len(content),
        dropped,
        dropped / len(content) * 100,
        url,
    )
    return content[:limit]


def _get_max_response_bytes() -> int:
    default = int(PROJ_CONFIG.get("max_fetch_bytes", DEFAULT_MAX_RESPONSE_BYTES))
    raw = os.getenv("RSS_MAX_FETCH_BYTES")
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_fake_ip: bool = False,
) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if allow_fake_ip and isinstance(ip, ipaddress.IPv4Address) and ip in _FAKE_IP_NETWORK:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_fetch_url(url: str) -> str | None:
    """Validate URL scheme and guard against SSRF to private/reserved hosts.

    Returns an error message string if rejected, or None if allowed.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "错误: 无效的 URL"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"安全限制: 仅支持 http/https 协议 ({scheme or 'empty'})"

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return "错误: URL 缺少主机名"

    try:
        parsed_port = parsed.port
    except ValueError:
        return "错误: 无效的 URL"

    if (
        hostname == "localhost"
        or hostname.endswith(".local")
        or hostname.endswith(".localhost")
        or hostname.endswith(".internal")
    ):
        return f"安全限制: 禁止访问本地或内网地址 ({hostname})"

    # If hostname is an IP literal, reject blocked ranges immediately.
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        if _is_blocked_ip(ip):
            return f"安全限制: 禁止访问内网或保留 IP ({hostname})"
        return None

    # Resolve domain name; tolerate DNS failure gracefully (e.g. offline/mocked tests).
    port = parsed_port or (443 if scheme == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return None

    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        if not sockaddr:
            continue
        try:
            resolved_ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_blocked_ip(resolved_ip, allow_fake_ip=True):
            return f"安全限制: 目标域名解析到内网或保留地址 ({hostname} -> {resolved_ip})"

    return None


def _extract_content_type(response: object) -> str:
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return ""
    raw_ct = headers.get("Content-Type") or headers.get("content-type") or ""
    if not isinstance(raw_ct, str):
        return ""
    return raw_ct.split(";", 1)[0].strip().lower()


def _is_blocked_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    return content_type.startswith(_BLOCKED_CONTENT_TYPE_PREFIXES) or (
        content_type in _BLOCKED_CONTENT_TYPES
    )


def _read_response_bytes(response: object, max_bytes: int) -> bytes:
    """Stream response body up to max_bytes, raising ValueError if exceeded."""
    headers = getattr(response, "headers", None)
    if isinstance(headers, Mapping):
        raw_len = headers.get("Content-Length") or headers.get("content-length")
        if raw_len is not None:
            try:
                if int(str(raw_len).strip()) > max_bytes:
                    raise ValueError(f"响应体超过大小限制 ({max_bytes} 字节)")
            except (TypeError, ValueError) as exc:
                if "大小限制" in str(exc):
                    raise

    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        chunks_iter = iter_content(chunk_size=65536)
        try:
            iterator = iter(chunks_iter)
        except TypeError:
            iterator = None

        if iterator is not None:
            buf = bytearray()
            for chunk in iterator:
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ValueError(f"响应体超过大小限制 ({max_bytes} 字节)")
            if buf or isinstance(response, requests.Response):
                return bytes(buf)

    raw_content = getattr(response, "content", b"")
    if isinstance(raw_content, (bytes, bytearray)):
        if len(raw_content) > max_bytes:
            raise ValueError(f"响应体超过大小限制 ({max_bytes} 字节)")
        return bytes(raw_content)
    return b""


def fetch_article_content(url: str) -> str:
    """
    获取文章内容 - 使用 trafilatura 增强提取能力

    Args:
        url: 文章 URL

    Returns:
        文章正文内容
    """
    if not isinstance(url, str) or not url.strip():
        return "错误: 无效的 URL"
    url = url.strip()

    # 特定域名跳过抓取
    if "weixin.sogou.com" in url:
        return "内容跳过: 微信链接通常无法直接抓取，仅基于标题摘要分析"

    validation_error = _validate_fetch_url(url)
    if validation_error:
        return validation_error

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
        if proxy and "://" not in proxy:
            proxy = f"http://{proxy}"
        proxies = {"http": proxy, "https": proxy} if proxy else None

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        max_bytes = _get_max_response_bytes()

        # 直接使用 requests 获取，确保代理生效；手动处理重定向以在发起下一跳请求前校验 SSRF
        response = None
        current_url = url
        try:
            for hop in range(MAX_REDIRECTS + 1):
                response = requests.get(
                    current_url,
                    headers=headers,
                    proxies=proxies,
                    timeout=15,
                    stream=True,
                    allow_redirects=False,
                )
                if response.status_code in _REDIRECT_STATUS_CODES:
                    resp_headers = getattr(response, "headers", None)
                    location = None
                    if isinstance(resp_headers, Mapping):
                        location = resp_headers.get("Location") or resp_headers.get("location")
                    if isinstance(location, str) and location.strip():
                        close_fn = getattr(response, "close", None)
                        if callable(close_fn):
                            close_fn()
                        response = None
                        if hop >= MAX_REDIRECTS:
                            return "获取失败: 重定向次数过多"
                        next_url = urljoin(current_url, location.strip())
                        redirect_error = _validate_fetch_url(next_url)
                        if redirect_error:
                            return redirect_error
                        current_url = next_url
                        continue
                break

            if response is None:
                return "获取失败: 重定向次数过多"

            if response.status_code != 200:
                return f"获取失败: HTTP {response.status_code}"

            content_type = _extract_content_type(response)
            if _is_blocked_content_type(content_type):
                return f"内容跳过: 不支持的内容类型 ({content_type})"

            try:
                downloaded = _read_response_bytes(response, max_bytes)
            except ValueError as size_err:
                return f"获取失败: {size_err}"
        except Exception as req_err:
            return f"请求异常: {str(req_err)}"
        finally:
            if response is not None:
                close_fn = getattr(response, "close", None)
                if callable(close_fn):
                    close_fn()

        # 提取正文
        if downloaded:
            result = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False
            )
            if result:
                return _truncate_content(result, url)
            else:
                return "内容提取为空 (可能是纯JS渲染页面)"
        else:
            return "下载内容为空"

    except Exception as e:
        import traceback
        import sys

        traceback.print_exc(file=sys.stderr)
        return f"处理异常: {str(e)}"
