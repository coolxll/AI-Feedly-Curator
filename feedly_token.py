#!/usr/bin/env python3
"""CLI for checking, refreshing, and initializing Feedly credentials.

Usage:
  python feedly_token.py check
  python feedly_token.py refresh
  python feedly_token.py init
"""

import sys
import time

import requests

from rss_analyzer.feedly_auth import (
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
        print("🎉 Token 续期成功！")
    except requests.HTTPError as exc:
        print(f"❌ 续期失败: {exc.response.status_code} {exc.response.text}")
        if exc.response.status_code in (400, 403):
            print("   refresh_token 可能已失效，需要重新获取")
        raise SystemExit(1) from exc


def cmd_check() -> None:
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
                f"过期时间: {formatted_expiry} "
                f"(剩余 {remaining // 86400} 天 {(remaining % 86400) // 3600} 小时)"
            )
        else:
            print(f"⚠️  Token 已过期 ({formatted_expiry})")

    try:
        response = requests.get(
            "https://cloud.feedly.com/v3/profile",
            headers=get_feedly_headers(token),
            proxies=get_feedly_proxy(),
            timeout=15,
        )
        if response.status_code == 200:
            profile = response.json()
            print(
                "\n✅ Token 有效 — 用户: "
                f"{profile.get('givenName', '?')} {profile.get('familyName', '?')} "
                f"({profile.get('email', '?')})"
            )
            print(f"   Plan: {profile.get('plan', '?')}")
        elif response.status_code == 401:
            print("\n❌ Token 已过期 (401)")
            if refresh_token:
                print("   有 refresh_token，可以自动续期: python feedly_token.py refresh")
        else:
            print(f"\n⚠️  异常响应: {response.status_code}")
    except requests.RequestException as exc:
        print(f"\n❌ 请求失败: {exc}")


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "check"
    commands = {"init": cmd_init, "refresh": cmd_refresh, "check": cmd_check}
    handler = commands.get(command)
    if handler:
        handler()
        return

    executable = sys.argv[0] if argv is None else "feedly_token.py"
    print(f"用法: python {executable} [init|refresh|check]")
    print("  init    — 首次 PKCE 授权，获取 access_token + refresh_token")
    print("  refresh — 用 refresh_token 自动续期 access_token")
    print("  check   — 检查当前 token 状态")


if __name__ == "__main__":
    main()
