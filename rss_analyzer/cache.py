import sqlite3
import json
import os
import logging
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


def get_cached_score(article_id: str) -> dict | None:
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
        # 1. Save to SQLite
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Include title and url in the INSERT/UPDATE
        title = data.get("title", "")
        url = data.get("url", "")
        c.execute(
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
                datetime.now(),
            ),
        )
        conn.commit()
        conn.close()

        if not is_vector_store_enabled():
            logger.debug("Vector store disabled; skipped embedding persistence for %s", article_id)
            return

        # 2. Save to Vector Store (ChromaDB)
        try:
            # Local import to avoid circular dependency if cache is imported early
            from rss_analyzer.vector_store import vector_store
            payload = build_vector_store_payload(article_id, score, data)
            if payload:
                # Async-like: don't let vector store failure block main flow
                vector_store.add_article(
                    payload["article_id"],
                    payload["document_text"],
                    payload["metadata"],
                )
                logger.debug(f"Saved vector embedding for {article_id}")

        except Exception as ve:
            # Log but don't fail the whole operation
            logger.warning(f"Failed to save vector embedding: {ve}")

    except Exception as e:
        logger.error(f"Cache write error: {e}")


# Initialize on module load
init_db()
