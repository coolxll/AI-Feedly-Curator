#!/usr/bin/env python3
import json
import os
import struct
import sys
import traceback

from rss_analyzer.cache import get_cached_score


def _read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        return None
    if len(raw_length) != 4:
        return None
    message_length = struct.unpack('<I', raw_length)[0]
    if message_length == 0:
        return None
    message = sys.stdin.buffer.read(message_length)
    if not message:
        return None
    try:
        return json.loads(message.decode('utf-8'))
    except Exception:
        return None


def _send_message(payload: dict):
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


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
    cached = get_cached_score(article_id)
    return _normalize_item(article_id, cached)


def _handle_get_scores(msg: dict) -> dict:
    ids = msg.get("ids") or []
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
    while True:
        msg = _read_message()
        if msg is None:
            break
        try:
            response = _handle_message(msg)
        except Exception as exc:
            response = {
                "error": "exception",
                "detail": str(exc),
                "trace": traceback.format_exc(limit=3),
            }
        _send_message(response)


if __name__ == "__main__":
    main()
