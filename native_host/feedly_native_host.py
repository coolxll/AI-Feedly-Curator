#!/usr/bin/env python3
import json
import os
import struct
import sys
import traceback
import logging

# === 调试代码开始 ===
# 放到最前面，确保任何错误都能被记录
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native_host_debug.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("Native Host 启动...")
logging.info(f"Python解释器: {sys.executable}")
logging.info(f"当前工作目录: {os.getcwd()}")
logging.info(f"系统路径: {sys.path}")
# === 调试代码结束 ===

try:
    # 这一步是为了让它能找到上级目录的 rss_analyzer 包
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    # 设置数据库路径环境变量
    DB_PATH = os.path.join(PROJECT_ROOT, "rss_scores.db")
    os.environ["RSS_SCORES_DB"] = DB_PATH
    logging.info(f"设置 RSS_SCORES_DB: {DB_PATH}")

    from rss_analyzer.cache import get_cached_score
    logging.info("成功导入 rss_analyzer.cache")
except Exception:
    logging.exception("导入模块失败！")
    sys.exit(1)


def _read_message():
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) == 0:
            logging.info("stdin closed")
            return None
        if len(raw_length) != 4:
            logging.error(f"Invalid length header: {len(raw_length)} bytes")
            return None
        message_length = struct.unpack('<I', raw_length)[0]
        if message_length == 0:
            logging.warning("Message length is 0")
            return None
        message = sys.stdin.buffer.read(message_length)
        if not message:
            logging.error("Failed to read message body")
            return None
        try:
            decoded = json.loads(message.decode('utf-8'))
            logging.debug(f"Received message: {decoded.get('type', 'unknown')}")
            return decoded
        except Exception as e:
            logging.error(f"JSON decode error: {e}")
            return None
    except Exception:
        logging.exception("Read message exception")
        return None


def _send_message(payload: dict):
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        sys.stdout.buffer.write(struct.pack('<I', len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        logging.debug("Message sent successfully")
    except Exception:
        logging.exception("Send message exception")


def _normalize_item(article_id: str, cached: dict | None) -> dict:
    if not cached:
        return {
            "id": article_id,
            "score": None,
            "data": {},
            "updated_at": None,
            "found": False,
        }
    return {
        "id": article_id,
        "score": cached.get("score"),
        "data": cached.get("data") or {},
        "updated_at": cached.get("updated_at"),
        "found": True,
    }


def _handle_get_score(msg: dict) -> dict:
    article_id = msg.get("id")
    logging.info(f"Handling get_score for: {article_id}")
    cached = get_cached_score(article_id)
    logging.info(f"Cache result: {'Found' if cached else 'Not Found'}")
    return _normalize_item(article_id, cached)


def _handle_get_scores(msg: dict) -> dict:
    ids = msg.get("ids") or []
    logging.info(f"Handling get_scores for {len(ids)} items")
    items = {}
    for article_id in ids:
        cached = get_cached_score(article_id)
        items[article_id] = _normalize_item(article_id, cached)
    return {"items": items}


def _handle_health(_: dict) -> dict:
    return {"ok": True}


def _handle_message(msg: dict) -> dict:
    msg_type = msg.get("type")
    if msg_type == "get_score":
        return _handle_get_score(msg)
    if msg_type == "get_scores":
        return _handle_get_scores(msg)
    if msg_type == "health":
        return _handle_health(msg)
    return {"error": "unknown_type"}


def main():
    logging.info("进入主循环")
    while True:
        msg = _read_message()
        if msg is None:
            break
        try:
            response = _handle_message(msg)
        except Exception as exc:
            logging.exception("处理消息时发生异常")
            response = {
                "error": "exception",
                "detail": str(exc),
                "trace": traceback.format_exc(limit=3),
            }
        _send_message(response)


if __name__ == "__main__":
    main()
