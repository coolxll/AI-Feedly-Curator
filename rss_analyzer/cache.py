import sqlite3
import json
import os
import logging
from datetime import datetime

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
        expires_at = datetime.now().isoformat()
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

        # 2. Save to Vector Store (ChromaDB)
        # Only save if we have meaningful text (summary or content)
        try:
            # Local import to avoid circular dependency if cache is imported early
            from rss_analyzer.vector_store import vector_store

            # Double check metadata if they are missing but might be in the row
            # (Though in this specific function we already have them from data.get)
            final_title = title
            final_url = url

            text_content = data.get("summary") or data.get("content") or ""

            # Construct a meaningful document for embedding
            # Prefer: Title + Summary. If no summary, Title + Content snippet.
            document_text = ""
            if final_title:
                document_text += f"Title: {final_title}\n"
            if text_content:
                document_text += f"Content: {text_content}"

            if document_text.strip():
                # Prepare metadata
                metadata = {
                    "score": score,
                    "title": final_title[:100] if final_title else "Untitled",
                    "updated_at": datetime.now().isoformat(),
                }

                # Add URL if available
                if final_url:
                    metadata["url"] = final_url

                # Async-like: don't let vector store failure block main flow
                vector_store.add_article(article_id, document_text, metadata)
                logger.debug(f"Saved vector embedding for {article_id}")

        except Exception as ve:
            # Log but don't fail the whole operation
            logger.warning(f"Failed to save vector embedding: {ve}")

    except Exception as e:
        logger.error(f"Cache write error: {e}")


# Initialize on module load
init_db()
