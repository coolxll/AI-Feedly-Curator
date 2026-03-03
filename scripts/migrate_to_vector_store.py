#!/usr/bin/env python3
"""
Vector Store Migration Script

This script migrates historical data from SQLite database to ChromaDB vector store.
Supports checkpoint resume.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv(os.path.join(project_root, ".env"))

# Need to set up path before importing local modules
from rss_analyzer.cache import DB_PATH  # noqa: E402
from rss_analyzer.vector_store import vector_store  # noqa: E402


DEFAULT_CHECKPOINT_FILE = os.path.join(project_root, "data", "vector_migration_checkpoint.json")


def load_checkpoint(checkpoint_file: str) -> dict:
    if not os.path.exists(checkpoint_file):
        return {}
    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load checkpoint file {checkpoint_file}: {e}")
        return {}


def save_checkpoint(checkpoint_file: str, state: dict) -> None:
    os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
    tmp_file = f"{checkpoint_file}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, checkpoint_file)


def reset_checkpoint(checkpoint_file: str) -> None:
    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)
        print(f"🧹 Checkpoint removed: {checkpoint_file}")


def _build_migration_item(row):
    rowid, article_id, score, data_str, title, url, updated_at = row

    # Parse the data JSON
    try:
        data = json.loads(data_str) if data_str else {}
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON for article {article_id}, skipping...")
        return rowid, article_id, None, "skipped"

    # Enhance data with title and URL from separate columns if not in data
    if not data.get("title") and title and title.strip():
        data["title"] = title
    if not data.get("url") and url and url.strip():
        data["url"] = url

    # Try to extract title and URL from the data dictionary if they exist
    article_title = data.get("title", "") or title or ""
    article_url = data.get("url", "") or url or ""

    # Use summary or content for the embedding text
    text_content = data.get("summary") or data.get("content") or ""

    # Only proceed if we have meaningful content to embed
    if not text_content.strip() and not article_title.strip():
        return rowid, article_id, None, "skipped"

    # Construct document for embedding
    document_text = ""
    if article_title.strip():
        document_text += f"Title: {article_title}\n"
    if text_content.strip():
        document_text += f"Content: {text_content}"

    if not document_text.strip():
        return rowid, article_id, None, "skipped"

    metadata = {
        "score": score,
        "title": article_title[:100] if article_title.strip() else "Untitled",
        "updated_at": updated_at.isoformat()
        if hasattr(updated_at, "isoformat")
        else str(updated_at),
    }
    if article_url.strip():
        metadata["url"] = article_url

    return rowid, article_id, (document_text, metadata), "ready"


def _safe_metadata(metadata: Optional[dict]) -> dict:
    safe = {}
    if not metadata:
        return safe
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            safe[k] = v
        else:
            safe[k] = str(v)
    return safe


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def process_batch(batch, embedding_batch_size=64):
    """Process a batch of articles with batched embedding+upsert."""
    if not batch:
        return 0, 0

    try:
        vector_store._get_client()
    except Exception as e:
        logger.error(f"Failed to initialize vector store client for batch write: {e}")
        return 0, len(batch)

    if not vector_store.collection:
        return 0, len(batch)

    ids = [item[0] for item in batch]
    docs = [item[1] for item in batch]
    metadatas = [_safe_metadata(item[2]) for item in batch]

    try:
        embeddings = None
        if vector_store.embedding_fn:
            embeddings = []
            for doc_chunk in _chunked(docs, embedding_batch_size):
                embeddings.extend(vector_store.embedding_fn(doc_chunk))

        vector_store.collection.upsert(
            ids=ids,
            documents=docs,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return len(batch), 0
    except Exception as batch_error:
        logger.warning(
            "Batch upsert failed (%s). Falling back to per-item writes for this batch.",
            batch_error,
        )

    success_count = 0
    failed_count = 0
    for article_id, document_text, metadata in batch:
        try:
            success = vector_store.add_article(article_id, document_text, metadata)
            if success:
                success_count += 1
            else:
                failed_count += 1
        except Exception as item_error:
            failed_count += 1
            logger.error(
                f"Failed to add article {article_id} to vector store: {item_error}"
            )
    return success_count, failed_count


def migrate_from_sqlite_to_vector_store(
    batch_size=100,
    checkpoint_file=DEFAULT_CHECKPOINT_FILE,
    resume=True,
    embedding_batch_size=64,
):
    """Migrate data from SQLite to vector store in batches with checkpoint resume."""
    print("🔄 Starting migration from SQLite to vector store...")

    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()

    sqlite_cursor.execute("SELECT COUNT(*) FROM article_scores")
    sqlite_total = sqlite_cursor.fetchone()[0]
    vector_count = vector_store.get_article_count()

    print(f"📊 SQLite records: {sqlite_total}")
    print(f"📊 Vector store records: {vector_count}")

    last_rowid = 0
    migrated_count = 0
    skipped_count = 0
    failed_count = 0
    processed_count = 0

    checkpoint = load_checkpoint(checkpoint_file) if resume else {}
    if checkpoint and checkpoint.get("db_path") == DB_PATH:
        last_rowid = int(checkpoint.get("last_rowid", 0))
        migrated_count = int(checkpoint.get("migrated_count", 0))
        skipped_count = int(checkpoint.get("skipped_count", 0))
        failed_count = int(checkpoint.get("failed_count", 0))
        processed_count = int(checkpoint.get("processed_count", 0))
        print(
            f"♻️ Resume enabled: last_rowid={last_rowid}, processed={processed_count}, "
            f"migrated={migrated_count}, skipped={skipped_count}, failed={failed_count}"
        )

    while True:
        sqlite_cursor.execute(
            """
            SELECT rowid, article_id, score, data, title, url, updated_at
            FROM article_scores
            WHERE rowid > ?
            ORDER BY rowid
            LIMIT ?
            """,
            (last_rowid, batch_size),
        )
        rows = sqlite_cursor.fetchall()
        if not rows:
            break

        ready_batch = []
        for row in rows:
            rowid, article_id, payload, status = _build_migration_item(row)
            last_rowid = rowid
            processed_count += 1
            if status == "skipped":
                skipped_count += 1
                continue
            document_text, metadata = payload
            ready_batch.append((article_id, document_text, metadata))

        if ready_batch:
            ok_count, err_count = process_batch(
                ready_batch,
                embedding_batch_size=embedding_batch_size,
            )
            migrated_count += ok_count
            failed_count += err_count

        checkpoint_state = {
            "db_path": DB_PATH,
            "last_rowid": last_rowid,
            "processed_count": processed_count,
            "migrated_count": migrated_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "completed": False,
        }
        save_checkpoint(checkpoint_file, checkpoint_state)

        print(
            f"   Processed {processed_count}/{sqlite_total} "
            f"(migrated={migrated_count}, skipped={skipped_count}, failed={failed_count})..."
        )

    sqlite_conn.close()

    new_vector_count = vector_store.get_article_count()
    final_state = {
        "db_path": DB_PATH,
        "last_rowid": last_rowid,
        "processed_count": processed_count,
        "migrated_count": migrated_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "completed": True,
    }
    save_checkpoint(checkpoint_file, final_state)

    print("\n✅ Migration completed!")
    print(f"📊 Records processed: {processed_count}")
    print(f"📊 Records migrated: {migrated_count}")
    print(f"📊 Records skipped: {skipped_count}")
    print(f"📊 Records failed: {failed_count}")
    print(f"📊 Vector store final count: {new_vector_count}")
    print(f"🗂️  Checkpoint saved: {checkpoint_file}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migrate SQLite article_scores to ChromaDB with checkpoint resume."
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size.")
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=64,
        help="Embedding batch size per API call.",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=DEFAULT_CHECKPOINT_FILE,
        help="Checkpoint file path.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing checkpoint and start from beginning.",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Delete checkpoint file before starting.",
    )
    return parser.parse_args()


def main():
    print("🚀 Vector Store Migration Tool")
    print("=" * 50)

    # Show current status
    vector_count = vector_store.get_article_count()
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute("SELECT COUNT(*) FROM article_scores")
    sqlite_total = sqlite_cursor.fetchone()[0]
    sqlite_conn.close()

    print("Current status:")
    print(f"  - SQLite records: {sqlite_total}")
    print(f"  - Vector store records: {vector_count}")
    print()

    args = parse_args()

    if args.batch_size <= 0:
        print("❌ --batch-size must be > 0")
        return
    if args.embedding_batch_size <= 0:
        print("❌ --embedding-batch-size must be > 0")
        return

    if args.reset_checkpoint:
        reset_checkpoint(args.checkpoint_file)

    checkpoint = load_checkpoint(args.checkpoint_file) if not args.no_resume else {}
    resume_hint = ""
    if checkpoint and not args.no_resume and not checkpoint.get("completed"):
        resume_hint = (
            f"\n   检测到断点: last_rowid={checkpoint.get('last_rowid', 0)}, "
            f"processed={checkpoint.get('processed_count', 0)}"
        )

    if vector_count >= sqlite_total and not resume_hint:
        print(
            "ℹ️  Vector store already has equal or more records than SQLite. Migration may not be needed."
        )
        return

    confirm = input(
        f"⚠️  This will migrate {sqlite_total} records to vector store. Continue? (y/N): {resume_hint}"
    )
    if confirm.lower() == "y":
        migrate_from_sqlite_to_vector_store(
            batch_size=args.batch_size,
            checkpoint_file=args.checkpoint_file,
            resume=not args.no_resume,
            embedding_batch_size=args.embedding_batch_size,
        )
    else:
        print("   Migration cancelled.")


if __name__ == "__main__":
    main()
