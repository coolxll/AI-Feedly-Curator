import sqlite3
import os
import json
from rss_analyzer.cache import DB_PATH
from rss_analyzer.vector_store import vector_store

def repair_vector_metadata():
    print(f"Connecting to DB: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 获取 SQLite 中所有的文章信息
    c.execute("SELECT article_id, title, url, score, data FROM article_scores")
    rows = c.fetchall()

    print(f"Found {len(rows)} articles in SQLite. Checking vector store...")

    repaired_count = 0
    for article_id, title, url, score, data_json in rows:
        # 尝试解析 data 中的内容
        try:
            data = json.loads(data_json)
        except:
            data = {}

        # 确定最终标题和链接
        final_title = title or data.get("title", "Untitled")
        final_url = url or data.get("url", "")

        if not final_title or final_title == "Untitled":
            # 看看能不能从 content 里抠一点
            content = data.get("summary") or data.get("content") or ""
            if content and len(content) > 10:
                final_title = content[:50].replace("\n", " ") + "..."

        # 更新向量数据库中的元数据
        # 注意：ChromaDB 的 update/upsert 如果不提供 document 会保留原有的 document
        metadata = {
            "score": score,
            "title": final_title[:100],
            "url": final_url
        }

        # 只有在确实有信息时才更新
        if final_url or (final_title and final_title != "Untitled"):
            # 获取原有的 document 以免丢失
            try:
                res = vector_store.collection.get(ids=[article_id], include=["documents", "metadatas"])
                if res["ids"]:
                    doc = res["documents"][0]
                    existing_meta = res["metadatas"][0]

                    # 只有当原有元数据缺失信息时才更新
                    if not existing_meta.get("url") or existing_meta.get("title") == "Untitled":
                        # 保留原有的 updated_at
                        if "updated_at" in existing_meta:
                            metadata["updated_at"] = existing_meta["updated_at"]

                        vector_store.collection.update(
                            ids=[article_id],
                            metadatas=[metadata]
                        )
                        repaired_count += 1
            except Exception as e:
                print(f"Error checking/updating {article_id}: {e}")

    conn.close()
    print(f"Repair complete. Repaired {repaired_count} entries.")

if __name__ == "__main__":
    repair_vector_metadata()
