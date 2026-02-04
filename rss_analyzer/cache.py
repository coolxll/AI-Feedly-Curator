import sqlite3
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('RSS_SCORES_DB', os.path.join(os.getcwd(), 'rss_scores.db'))

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS article_scores (
                article_id TEXT PRIMARY KEY,
                score REAL,
                data TEXT,
                updated_at TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init cache db: {e}")

def get_cached_score(article_id: str) -> dict | None:
    if not article_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT score, data, updated_at FROM article_scores WHERE article_id = ?', (article_id,))
        row = c.fetchone()
        conn.close()

        if row:
            try:
                data = json.loads(row[1])
            except Exception:
                data = {}
            updated_at = row[2]
            if hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()
            return {
                'score': row[0],
                'data': data,
                'updated_at': updated_at
            }
    except Exception as e:
        logger.error(f"Cache read error: {e}")
    return None

def save_cached_score(article_id: str, score: float, data: dict):
    if not article_id:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO article_scores (article_id, score, data, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (article_id, score, json.dumps(data, ensure_ascii=False), datetime.now()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Cache write error: {e}")

# Initialize on module load
init_db()
