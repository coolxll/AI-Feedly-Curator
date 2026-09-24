import sqlite3
import json
import os
import logging
import threading
from datetime import datetime
from typing import Any

from rss_analyzer.config import is_vector_store_enabled

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("RSS_SCORES_DB", os.path.join(os.getcwd(), "rss_scores.db"))


def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Create table with additional title and url columns
        c.execute("""
            CREATE TABLE IF NOT EXISTS article_scores (
                article_id TEXT PRIMARY KEY,
                score REAL,
                data TEXT,
                title TEXT,
                url TEXT,
                updated_at TIMESTAMP
            )
        """)
        # Create table for general app cache (e.g. trending topics)
        c.execute("""
            CREATE TABLE IF NOT EXISTS app_cache (
                cache_key TEXT PRIMARY KEY,
                cache_value TEXT,
                expires_at TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS vector_index_outbox (
                article_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute(
            "UPDATE vector_index_outbox SET status = 'pending' WHERE status = 'processing'"
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init cache db: {e}")


def get_app_cache(key: str) -> dict | None:
    """Retrieve a value from the app cache if not expired"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT cache_value, expires_at FROM app_cache WHERE cache_key = ?", (key,)
        )
        row = c.fetchone()
        conn.close()

        if row:
            value_json, expires_at_str = row
            # Check expiration
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at > datetime.now():
                return json.loads(value_json)
            else:
                # Cleanup expired
                delete_app_cache(key)
    except Exception as e:
        logger.error(f"App cache read error: {e}")
    return None


def set_app_cache(key: str, value: dict, ttl_seconds: int):
    """Store a value in the app cache with a TTL"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Calculate expiration
        from datetime import timedelta

        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()

        c.execute(
            "INSERT OR REPLACE INTO app_cache (cache_key, cache_value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), expires_at),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"App cache write error: {e}")


def delete_app_cache(key: str):
    """Delete a value from the app cache"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM app_cache WHERE cache_key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"App cache delete error: {e}")


def get_cached_score(
    article_id: str,
    *,
    analysis_fingerprint: str | None = None,
    content_hash: str | None = None,
) -> dict | None:
    if not article_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Select with new title and url columns
        c.execute(
            "SELECT score, data, title, url, updated_at FROM article_scores WHERE article_id = ?",
            (article_id,),
        )
        row = c.fetchone()
        conn.close()

        if row:
            try:
                data = json.loads(row[1])
            except Exception:
                data = {}

            if analysis_fingerprint is not None and data.get(
                "analysis_fingerprint"
            ) != analysis_fingerprint:
                return None
            if content_hash is not None and data.get("content_hash") != content_hash:
                return None

            # Enhance data with title and url from separate columns if not in data
            if not data.get("title") and row[2]:  # title column
                data["title"] = row[2]
            if not data.get("url") and row[3]:  # url column
                data["url"] = row[3]

            updated_at = row[4]
            if hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()
            return {"score": row[0], "data": data, "updated_at": updated_at}
    except Exception as e:
        logger.error(f"Cache read error: {e}")
    return None


def iter_cached_scores() -> list[dict[str, Any]]:
    """
    Return all cached article scores with normalized data payloads.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            SELECT article_id, score, data, title, url, updated_at
            FROM article_scores
            ORDER BY updated_at DESC
            """
        )
        rows = c.fetchall()
        conn.close()

        items = []
        for article_id, score, data_json, title, url, updated_at in rows:
            try:
                data = json.loads(data_json) if data_json else {}
            except Exception:
                data = {}

            if title and not data.get("title"):
                data["title"] = title
            if url and not data.get("url"):
                data["url"] = url

            if hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()

            items.append(
                {
                    "article_id": article_id,
                    "score": score,
                    "data": data,
                    "updated_at": updated_at,
                }
            )

        return items
    except Exception as e:
        logger.error(f"Cache list error: {e}")
        return []


def build_vector_store_payload(
    article_id: str, score: float, data: dict, updated_at: str | None = None
) -> dict[str, Any] | None:
    """
    Build a normalized vector-store payload from cached article data.
    """
    title = data.get("title", "")
    url = data.get("url", "")
    text_content = data.get("summary") or data.get("content") or ""

    parts = []
    if title:
        parts.append(f"Title: {title}")
    if text_content:
        parts.append(f"Content: {text_content}")

    document_text = "\n".join(parts).strip()
    if not document_text:
        return None

    metadata = {
        "score": score,
        "title": title[:100] if title else "Untitled",
        "updated_at": updated_at or datetime.now().isoformat(),
    }
    if url:
        metadata["url"] = url

    return {
        "article_id": article_id,
        "document_text": document_text,
        "metadata": metadata,
    }


def save_cached_score(article_id: str, score: float, data: dict):
    if not article_id:
        return
    try:
        vector_enabled = is_vector_store_enabled()
        updated_at = datetime.now().isoformat()
        vector_payload = (
            build_vector_store_payload(article_id, score, data, updated_at)
            if vector_enabled
            else None
        )
        title = data.get("title", "")
        url = data.get("url", "")
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO article_scores (article_id, score, data, title, url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    score,
                    json.dumps(data, ensure_ascii=False),
                    title,
                    url,
                    updated_at,
                ),
            )
            if vector_payload:
                conn.execute(
                    """
                    INSERT INTO vector_index_outbox (
                        article_id, payload, status, attempts, last_error, updated_at
                    ) VALUES (?, ?, 'pending', 0, NULL, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                        payload = excluded.payload,
                        status = 'pending',
                        attempts = 0,
                        last_error = NULL,
                        updated_at = excluded.updated_at
                    """,
                    (
                        article_id,
                        json.dumps(vector_payload, ensure_ascii=False),
                        updated_at,
                    ),
                )

        if not vector_enabled:
            logger.debug("Vector store disabled; skipped embedding persistence for %s", article_id)
            return
        if vector_payload:
            start_vector_index_worker()
            _VECTOR_WORKER_EVENT.set()

    except Exception as e:
        logger.error(f"Cache write error: {e}")


def get_vector_index_queue_stats() -> dict[str, int]:
    try:
        with sqlite3.connect(DB_PATH) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM vector_index_outbox GROUP BY status"
            ).fetchall()
        stats = {"pending": 0, "processing": 0, "failed": 0}
        stats.update({status: count for status, count in rows})
        stats["total"] = sum(rows_count for _, rows_count in rows)
        return stats
    except Exception as exc:
        logger.error("Failed to read vector index queue stats: %s", exc)
        return {"pending": 0, "processing": 0, "failed": 0, "total": 0}


def process_vector_index_queue(limit: int = 20) -> dict[str, int]:
    processed = 0
    failed = 0
    for _ in range(max(1, limit)):
        connection = sqlite3.connect(DB_PATH, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT article_id, payload FROM vector_index_outbox
                WHERE status = 'pending' ORDER BY updated_at ASC LIMIT 1
                """
            ).fetchone()
            if not row:
                connection.commit()
                break
            article_id, payload_json = row
            connection.execute(
                """
                UPDATE vector_index_outbox
                SET status = 'processing', attempts = attempts + 1, updated_at = ?
                WHERE article_id = ?
                """,
                (datetime.now().isoformat(), article_id),
            )
            connection.commit()
        finally:
            connection.close()

        try:
            from rss_analyzer.vector_store import vector_store

            payload = json.loads(payload_json)
            if not vector_store.add_article(
                payload["article_id"],
                payload["document_text"],
                payload["metadata"],
            ):
                raise RuntimeError("Vector store rejected article")
            with sqlite3.connect(DB_PATH) as connection:
                connection.execute(
                    """
                    DELETE FROM vector_index_outbox
                    WHERE article_id = ? AND status = 'processing' AND payload = ?
                    """,
                    (article_id, payload_json),
                )
            processed += 1
        except Exception as exc:
            failed += 1
            logger.warning("Vector indexing failed for %s: %s", article_id, exc)
            with sqlite3.connect(DB_PATH) as connection:
                connection.execute(
                    """
                    UPDATE vector_index_outbox
                    SET status = 'failed', last_error = ?, updated_at = ?
                    WHERE article_id = ? AND status = 'processing' AND payload = ?
                    """,
                    (str(exc), datetime.now().isoformat(), article_id, payload_json),
                )
    return {"processed": processed, "failed": failed, **get_vector_index_queue_stats()}


def retry_vector_index_queue(*, wake_worker: bool = True) -> dict[str, int]:
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            """
            UPDATE vector_index_outbox
            SET status = 'pending', last_error = NULL, updated_at = ?
            WHERE status = 'failed'
            """,
            (datetime.now().isoformat(),),
        )
    if wake_worker:
        start_vector_index_worker()
        _VECTOR_WORKER_EVENT.set()
    return {"retried": cursor.rowcount, **get_vector_index_queue_stats()}


_VECTOR_WORKER_EVENT = threading.Event()
_VECTOR_WORKER_LOCK = threading.Lock()
_VECTOR_WORKER_STARTED = False


def _vector_worker() -> None:
    while True:
        _VECTOR_WORKER_EVENT.wait(timeout=5)
        _VECTOR_WORKER_EVENT.clear()
        if not is_vector_store_enabled():
            continue
        result = process_vector_index_queue(limit=20)
        if result["pending"]:
            _VECTOR_WORKER_EVENT.set()


def start_vector_index_worker() -> None:
    global _VECTOR_WORKER_STARTED
    with _VECTOR_WORKER_LOCK:
        if _VECTOR_WORKER_STARTED:
            return
        thread = threading.Thread(
            target=_vector_worker,
            name="rss-vector-index-worker",
            daemon=True,
        )
        thread.start()
        _VECTOR_WORKER_STARTED = True


# Initialize on module load
init_db()
if is_vector_store_enabled() and get_vector_index_queue_stats()["pending"]:
    start_vector_index_worker()
    _VECTOR_WORKER_EVENT.set()
