#!/usr/bin/env python3
"""
Feedly Token 管理工具 — 支持 Web Session refresh + OAuth2 PKCE init

用法：
  python3 feedly_token.py check    — 检查当前 token 状态
  python3 feedly_token.py refresh  — 用 refresh_token 自动续期
  python3 feedly_token.py init     — 首次 PKCE 授权（浏览器交互）

位置：/mnt/c/Workspace/Personal/rss-opml/feedly_token.py
      ~/.hermes/skills/research/feedly-rss/scripts/feedly_token.py

Token 来源说明：
  - Web session token（从浏览器 localStorage 提取）：refresh 用 client_id=feedly，有效期 7 天
  - OAuth2 PKCE token（通过 init 命令获取）：refresh 用 client_id=feedlydev，有效期 30 天
  - 脚本自动检测：先试 feedly，失败再试 feedlydev
"""
import hashlib, base64, secrets, json, sys, os, time, urllib.parse
import requests

DEFAULT_CONFIG_CANDIDATES = [
    os.environ.get("FEEDLY_CONFIG_PATH", ""),
    os.path.join(os.getcwd(), "feedly_config.json"),
    "/mnt/c/Workspace/Personal/rss-opml/feedly_config.json",
]
DEFAULT_PROXY_URL = os.environ.get("FEEDLY_PROXY_URL", "http://127.0.0.1:7890")

# OAuth2 PKCE 配置（init 用）
PKCE_CLIENT_ID = "feedlydev"
PKCE_CLIENT_SECRET = "feedlydev"
AUTH_URL = "https://cloud.feedly.com/v3/auth/auth"
TOKEN_URL = "https://cloud.feedly.com/v3/auth/token"
REDIRECT_URI = "https://cloud.feedly.com/v3/auth/dev"
SCOPE = "https://cloud.feedly.com/subscriptions"

# Web session refresh 配置（refresh 用）
# 2026-07-01 验证：web session 的 refresh_token 只能用 client_id=feedly，
# 用 feedlydev 会返回 "invalid refresh_token"
WEB_CLIENT_ID = "feedly"


def resolve_config_path():
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate:
            return candidate
    return "feedly_config.json"


CONFIG_PATH = resolve_config_path()
PROXY = {"http": DEFAULT_PROXY_URL, "https": DEFAULT_PROXY_URL} if DEFAULT_PROXY_URL else None


def generate_pkce():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def build_auth_url(code_challenge):
    params = {
        "client_id": PKCE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code, code_verifier):
    """OAuth2 PKCE: 用 authorization_code 换取 tokens"""
    resp = requests.post(TOKEN_URL, json={
        "grant_type": "authorization_code",
        "client_id": PKCE_CLIENT_ID,
        "client_secret": PKCE_CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }, proxies=PROXY, timeout=15)
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token):
    """用 refresh_token 续期 access_token

    2026-07-01 验证：
    - Web session refresh_token → client_id=feedly（无 secret），有效期 7 天
    - OAuth2 PKCE refresh_token → client_id=feedlydev（带 secret），有效期 30 天
    先试 feedly，失败再试 feedlydev
    """
    # 方式1: web session refresh (client_id=feedly, 无 secret)
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": WEB_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, proxies=PROXY, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass

    # 方式2: OAuth2 PKCE refresh (client_id=feedlydev, 带 secret)
    resp = requests.post(TOKEN_URL, data={
        "client_id": PKCE_CLIENT_ID,
        "client_secret": PKCE_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, proxies=PROXY, timeout=15)
    resp.raise_for_status()
    return resp.json()


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(token_data):
    config = load_config()
    config["token"] = token_data["access_token"]
    config["user_id"] = token_data.get("id", config.get("user_id", ""))
    config["refresh_token"] = token_data.get("refresh_token", config.get("refresh_token", ""))
    expires_in = token_data.get("expires_in", 604800)
    config["token_expires_in"] = expires_in
    config["token_expires_at"] = int(time.time()) + expires_in
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n✅ 配置已保存到 {CONFIG_PATH}")
    print(f"   access_token: {token_data['access_token'][:30]}...")
    rt = token_data.get("refresh_token", "")
    print(f"   refresh_token: {rt[:30] if rt else 'N/A'}...")
    print(f"   有效期: {expires_in} 秒 ({expires_in // 86400} 天)")
    print(f"   过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(config['token_expires_at']))}")


def cmd_init():
    code_verifier, code_challenge = generate_pkce()
    auth_url = build_auth_url(code_challenge)
    print("=" * 60)
    print("Feedly OAuth2 PKCE 授权流程")
    print("=" * 60)
    print(f"\n1. 在浏览器中打开以下 URL 并完成授权：\n")
    print(f"   {auth_url}\n")
    print("2. 授权后浏览器会跳转到 feedly.com/v3/auth/dev?code=xxx")
    print("3. 复制 URL 中 code= 后面的值粘贴到下方\n")
    code = input("请输入 authorization_code: ").strip()
    if not code:
        print("❌ 未输入 code，退出")
        sys.exit(1)
    print("\n正在换取 tokens...")
    try:
        tokens = exchange_code(code, code_verifier)
        save_config(tokens)
        print("\n🎉 首次授权成功！后续可用 'refresh' 命令自动续期。")
    except requests.HTTPError as e:
        print(f"❌ 换取 token 失败: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def cmd_refresh():
    config = load_config()
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        print("❌ 没有找到 refresh_token")
        print("   获取方式：浏览器登录 feedly.com → F12 Console → localStorage.getItem('feedlyRefreshToken')")
        print("   或运行 JSON.stringify({...}) 后复制 refreshToken 字段")
        sys.exit(1)
    print("正在用 refresh_token 续期...")
    try:
        tokens = refresh_access_token(refresh_token)
        if "refresh_token" not in tokens or not tokens["refresh_token"]:
            tokens["refresh_token"] = refresh_token
        save_config(tokens)
        print("🎉 Token 续期成功！")
    except requests.HTTPError as e:
        print(f"❌ 续期失败: {e.response.status_code} {e.response.text}")
        if e.response.status_code in (400, 403):
            print("   refresh_token 可能已失效，需要重新获取")
        sys.exit(1)


def cmd_check():
    config = load_config()
    token = config.get("token", "")
    refresh_token = config.get("refresh_token", "")
    expires_at = config.get("token_expires_at", 0)

    print(f"当前 access_token: {token[:40]}..." if token else "❌ 没有 access_token")
    print(f"当前 refresh_token: {refresh_token[:40]}..." if refresh_token else "⚠️  没有 refresh_token")

    if expires_at:
        now = int(time.time())
        remaining = expires_at - now
        if remaining > 0:
            print(f"过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))} (剩余 {remaining // 86400} 天 {(remaining % 86400) // 3600} 小时)")
        else:
            print(f"⚠️  Token 已过期 ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))})")

    try:
        resp = requests.get(
            "https://cloud.feedly.com/v3/profile",
            headers={"Authorization": "OAuth " + token},
            proxies=PROXY, timeout=15
        )
        if resp.status_code == 200:
            profile = resp.json()
            print(f"\n✅ Token 有效 — 用户: {profile.get('givenName', '?')} {profile.get('familyName', '?')} ({profile.get('email', '?')})")
            print(f"   Plan: {profile.get('plan', '?')}")
        elif resp.status_code == 401:
            print("\n❌ Token 已过期 (401)")
            if refresh_token:
                print("   有 refresh_token，可以自动续期: python3 feedly_token.py refresh")
        else:
            print(f"\n⚠️  异常响应: {resp.status_code}")
    except Exception as e:
        print(f"\n❌ 请求失败: {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "init":
        cmd_init()
    elif cmd == "refresh":
        cmd_refresh()
    elif cmd == "check":
        cmd_check()
    else:
        print(f"用法: python3 {sys.argv[0]} [init|refresh|check]")
        print("  init    — 首次 PKCE 授权，获取 access_token + refresh_token")
        print("  refresh — 用 refresh_token 自动续期 access_token")
        print("  check   — 检查当前 token 状态")
