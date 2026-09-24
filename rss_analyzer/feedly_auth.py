"""Shared Feedly authentication, token persistence, and PKCE helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .config import PROJ_CONFIG


logger = logging.getLogger(__name__)

AUTH_URL = "https://cloud.feedly.com/v3/auth/auth"
TOKEN_URL = "https://cloud.feedly.com/v3/auth/token"
REDIRECT_URI = "https://cloud.feedly.com/v3/auth/dev"
SCOPE = "https://cloud.feedly.com/subscriptions"
WEB_CLIENT_ID = "feedly"
PKCE_CLIENT_ID = "feedlydev"
PKCE_CLIENT_SECRET = "feedlydev"
DEFAULT_TOKEN_LIFETIME_SECONDS = 604800


def resolve_feedly_config_file() -> str:
    """Resolve config from the environment, working tree, or package root."""
    configured_path = os.getenv("FEEDLY_CONFIG_PATH")
    if configured_path:
        return configured_path

    candidates = [
        os.path.join(os.getcwd(), "feedly_config.json"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "feedly_config.json"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return candidates[0]


FEEDLY_CONFIG_FILE = resolve_feedly_config_file()


def load_feedly_config(config_path: str | os.PathLike[str] | None = None) -> dict | None:
    path = Path(config_path or FEEDLY_CONFIG_FILE)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def save_feedly_config(
    config: dict,
    config_path: str | os.PathLike[str] | None = None,
) -> None:
    path = Path(config_path or FEEDLY_CONFIG_FILE)
    with path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2, ensure_ascii=False)


def get_feedly_headers(token: str) -> dict:
    return {"Authorization": f"OAuth {token}"}


def get_feedly_proxy() -> dict | None:
    proxy = (
        os.getenv("FEEDLY_PROXY_URL")
        or os.getenv("HTTP_PROXY")
        or os.getenv("HTTPS_PROXY")
        or PROJ_CONFIG.get("proxy")
    )
    if proxy and "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy} if proxy else None


def generate_pkce() -> tuple[str, str]:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def build_auth_url(code_challenge: str) -> str:
    params = {
        "client_id": PKCE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_authorization_code(code: str, code_verifier: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": PKCE_CLIENT_ID,
            "client_secret": PKCE_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        proxies=get_feedly_proxy(),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Refresh a web-session token first, then fall back to Feedly PKCE."""
    proxy = get_feedly_proxy()
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


def apply_token_data(config: dict, token_data: dict, *, now: int | None = None) -> dict:
    """Merge a token response into an existing Feedly config."""
    updated = dict(config)
    updated["token"] = token_data["access_token"]
    updated["user_id"] = token_data.get("id", updated.get("user_id", ""))
    updated["refresh_token"] = token_data.get("refresh_token") or updated.get(
        "refresh_token", ""
    )
    expires_in = int(token_data.get("expires_in", DEFAULT_TOKEN_LIFETIME_SECONDS))
    updated["token_expires_in"] = expires_in
    updated["token_expires_at"] = (int(time.time()) if now is None else now) + expires_in
    return updated


def persist_token_data(
    token_data: dict,
    config_path: str | os.PathLike[str] | None = None,
) -> dict:
    config = load_feedly_config(config_path) or {}
    updated = apply_token_data(config, token_data)
    save_feedly_config(updated, config_path)
    return updated


def refresh_feedly_config(
    config: dict,
    config_path: str | os.PathLike[str] | None = None,
) -> dict | None:
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        logger.error("Feedly token expired and no refresh_token is configured")
        return None

    try:
        token_data = refresh_access_token(refresh_token)
    except requests.RequestException as exc:
        logger.error("Feedly token refresh failed: %s", exc)
        return None

    updated = apply_token_data(config, token_data)
    config.clear()
    config.update(updated)
    save_feedly_config(config, config_path)
    logger.info("Feedly access_token refreshed successfully")
    return config
