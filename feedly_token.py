#!/usr/bin/env python3
"""CLI for checking, refreshing, and initializing Feedly credentials.

Usage:
  uv run python feedly_token.py check
  uv run python feedly_token.py refresh
  uv run python feedly_token.py init
  uv run python feedly_token.py check --auto-refresh
"""

import sys
import time

import requests

from rss_analyzer.feedly_auth import (
    FeedlyAuthError,
    build_auth_url,
    exchange_authorization_code as exchange_code,
    generate_pkce,
    get_feedly_headers,
    get_feedly_proxy,
    load_feedly_config,
    persist_token_data,
    refresh_access_token,
    resolve_feedly_config_file,
)


CONFIG_PATH = resolve_feedly_config_file()


def load_config() -> dict:
    return load_feedly_config(CONFIG_PATH) or {}


def save_config(token_data: dict) -> None:
    config = persist_token_data(token_data, CONFIG_PATH)
    expires_in = config["token_expires_in"]
    refresh_token = config.get("refresh_token", "")
    print(f"\n✅ 配置已保存到 {CONFIG_PATH}")
    print(f"   access_token: {config['token'][:30]}...")
    print(f"   refresh_token: {refresh_token[:30] if refresh_token else 'N/A'}...")
    print(f"   有效期: {expires_in} 秒 ({expires_in // 86400} 天)")
    print(
        "   过期时间: "
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(config['token_expires_at']))}"
    )


def cmd_init() -> None:
    code_verifier, code_challenge = generate_pkce()
    auth_url = build_auth_url(code_challenge)
    print("=" * 60)
    print("Feedly OAuth2 PKCE 授权流程")
    print("=" * 60)
    print("\n1. 在浏览器中打开以下 URL 并完成授权：\n")
    print(f"   {auth_url}\n")
    print("2. 授权后浏览器会跳转到 feedly.com/v3/auth/dev?code=xxx")
    print("3. 复制 URL 中 code= 后面的值粘贴到下方\n")
    code = input("请输入 authorization_code: ").strip()
    if not code:
        print("❌ 未输入 code，退出")
        raise SystemExit(1)

    print("\n正在换取 tokens...")
    try:
        save_config(exchange_code(code, code_verifier))
        print("\n🎉 首次授权成功！后续可用 'refresh' 命令自动续期。")
    except FeedlyAuthError as exc:
        print(f"❌ 换取 token 失败: {exc}")
        raise SystemExit(1) from exc
    except requests.HTTPError as exc:
        print(f"❌ 换取 token 失败: {exc.response.status_code} {exc.response.text}")
        raise SystemExit(1) from exc


def cmd_refresh() -> None:
    config = load_config()
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        print("❌ 没有找到 refresh_token")
        print(
            "   获取方式：浏览器登录 feedly.com → F12 Console → "
            "localStorage.getItem('feedlyRefreshToken')"
        )
        raise SystemExit(1)

    print("正在用 refresh_token 续期...")
    try:
        save_config(refresh_access_token(refresh_token))
    except FeedlyAuthError as exc:
        print(f"❌ 续期失败（refresh_token 被拒绝）: {exc}")
        print("   需要重新授权: uv run python feedly_token.py init")
        raise SystemExit(1) from exc
    except requests.HTTPError as exc:
        print(f"❌ 续期失败: {exc.response.status_code} {exc.response.text}")
        if exc.response.status_code in (400, 401, 403):
            print("   refresh_token 可能已失效，需要重新获取")
        raise SystemExit(1) from exc
    print("🎉 Token 续期成功！")

    # Verify the refreshed token is actually accepted by Feedly.
    try:
        status, profile = _probe_profile(load_config().get("token", ""))
    except requests.RequestException as exc:
        print(f"⚠️  续期后校验失败（连接/超时）: {exc}")
        raise SystemExit(2) from exc
    if status == 200 and profile:
        print(
            "✅ 校验通过 — 用户: "
            f"{profile.get('givenName', '?')} {profile.get('familyName', '?')}"
        )
    else:
        print(f"⚠️  续期后校验返回 {status}，请运行 uv run python feedly_token.py init")
        raise SystemExit(1)


def _probe_profile(token: str):
    """Call /v3/profile to verify the token is actually accepted by Feedly.

    Returns (status_code, payload_or_none). A 401 here is authoritative: the
    local token_expires_at timestamp can drift from reality, so only Feedly's
    answer is trusted.
    """
    response = requests.get(
        "https://cloud.feedly.com/v3/profile",
        headers=get_feedly_headers(token),
        proxies=get_feedly_proxy(),
        timeout=15,
    )
    payload = response.json() if response.status_code == 200 else None
    return response.status_code, payload


def cmd_check(auto_refresh: bool = False) -> None:
    config = load_config()
    token = config.get("token", "")
    refresh_token = config.get("refresh_token", "")
    expires_at = config.get("token_expires_at", 0)

    print(f"当前 access_token: {token[:40]}..." if token else "❌ 没有 access_token")
    print(
        f"当前 refresh_token: {refresh_token[:40]}..."
        if refresh_token
        else "⚠️  没有 refresh_token"
    )

    if expires_at:
        remaining = expires_at - int(time.time())
        formatted_expiry = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(expires_at)
        )
        if remaining > 0:
            print(
                f"本地记录的过期时间: {formatted_expiry} "
                f"(剩余 {remaining // 86400} 天 {(remaining % 86400) // 3600} 小时)"
            )
        else:
            print(f"⚠️  本地记录显示已过期 ({formatted_expiry})")

    if not token:
        print("\n❌ 没有可用的 access_token")
        raise SystemExit(1)

    try:
        status, profile = _probe_profile(token)
    except requests.RequestException as exc:
        # Connection/proxy problem — not an auth verdict.
        print(f"\n❌ 请求失败（连接/超时）: {exc}")
        raise SystemExit(2) from exc

    if status == 200 and profile:
        print(
            "\n✅ Token 有效 — 用户: "
            f"{profile.get('givenName', '?')} {profile.get('familyName', '?')} "
            f"({profile.get('email', '?')})"
        )
        print(f"   Plan: {profile.get('plan', '?')}")
        return

    if status == 401:
        print("\n❌ Token 已被 Feedly 拒绝 (401)，本地时间戳不可信")
        if not refresh_token:
            print("   没有 refresh_token，需要重新授权: uv run python feedly_token.py init")
            raise SystemExit(1)

        if not auto_refresh:
            print("   可用 --auto-refresh 立即续期，或运行: uv run python feedly_token.py refresh")
            raise SystemExit(1)

        print("   正在用 refresh_token 自动续期...")
        try:
            save_config(refresh_access_token(refresh_token))
        except requests.HTTPError as exc:
            print(f"❌ 续期失败: {exc.response.status_code} {exc.response.text}")
            print("   refresh_token 可能已失效，需要重新授权: uv run python feedly_token.py init")
            raise SystemExit(1) from exc

        # Re-verify with the freshly refreshed token.
        new_config = load_config()
        try:
            status, profile = _probe_profile(new_config.get("token", ""))
        except requests.RequestException as exc:
            print(f"❌ 续期后复检失败（连接/超时）: {exc}")
            raise SystemExit(2) from exc

        if status == 200 and profile:
            print(
                "\n✅ 续期成功，Token 有效 — 用户: "
                f"{profile.get('givenName', '?')} {profile.get('familyName', '?')} "
                f"({profile.get('email', '?')})"
            )
            return

        print(f"\n❌ 续期后 Feedly 仍返回 {status}，需要重新授权: uv run python feedly_token.py init")
        raise SystemExit(1)

    print(f"\n⚠️  异常响应: {status}")
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    auto_refresh = "--auto-refresh" in args
    positional = [a for a in args if not a.startswith("--")]
    command = positional[0] if positional else "check"

    if command == "check":
        cmd_check(auto_refresh=auto_refresh)
        return
    if command == "refresh":
        cmd_refresh()
        return
    if command == "init":
        cmd_init()
        return

    executable = sys.argv[0] if argv is None else "feedly_token.py"
    print(f"用法: uv run python {executable} [init|refresh|check] [--auto-refresh]")
    print("  init    — 首次 PKCE 授权，获取 access_token + refresh_token")
    print("  refresh — 用 refresh_token 自动续期 access_token")
    print("  check   — 实际调用 Feedly /v3/profile 校验 token")
    print("            --auto-refresh  401 时自动续期并复检")
    print("\n退出码: 0=有效, 1=认证失败, 2=连接/超时")


if __name__ == "__main__":
    main()
