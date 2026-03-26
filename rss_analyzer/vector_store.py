import os
import logging
import json
import hashlib
import sys
from typing import List, Dict, Any
from openai import OpenAI
from rss_analyzer.config import get_embedding_config

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb import Documents, EmbeddingFunction, Embeddings
    CHROMADB_IMPORT_ERROR = None
except Exception as chroma_import_error:
    chromadb = None
    Documents = list[str]
    Embeddings = list[list[float]]

    class EmbeddingFunction:
        pass

    CHROMADB_IMPORT_ERROR = chroma_import_error


def _build_chromadb_import_guidance() -> str:
    if CHROMADB_IMPORT_ERROR is None:
        return ""

    executable = sys.executable
    if "\\.venv\\" in executable.lower():
        return ""

    return (
        " Current interpreter is outside the project virtualenv "
        f"({executable}). Prefer running this project with "
        "`uv run python ...` or the project `.venv` interpreter to avoid "
        "global package version drift."
    )


class DashScopeEmbeddingFunction(EmbeddingFunction):
    """
    Custom EmbeddingFunction for ChromaDB using an OpenAI-compatible embedding API.
    """

    def __init__(self, model_name: str | None = None):
        embedding_config = get_embedding_config()
        self.api_key = embedding_config.api_key
        if not self.api_key:
            logger.warning(
                "No embedding API key found in environment variables "
                "(checked EMBEDDING_API_KEY, DASHSCOPE_API_KEY, ALIYUN_OPENAI_API_KEY, OPENAI_API_KEY)."
            )

        self.base_url = embedding_config.base_url
        self.model_name = model_name or embedding_config.model
        self.client = None

        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def __call__(self, input: Documents) -> Embeddings:
        if not self.client:
            logger.error(
                "Cannot generate embeddings: OpenAI client not initialized (missing API key)."
            )
            raise ValueError("OpenAI client not initialized (missing API key)")

        try:
            # Clean inputs - replace newlines to potentially improve performance/accuracy
            # though text-embedding-v3 handles them reasonably well.
            cleaned_input = [text.replace("\n", " ") for text in input]

            response = self.client.embeddings.create(
                input=cleaned_input, model=self.model_name
            )

            # OpenAI SDK returns a list of embedding objects.
            # We need to ensure they are sorted by index (usually are) and extract the vector.
            embeddings = [data.embedding for data in response.data]
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate embeddings via OpenAI SDK: {e}")
            raise


class ChromaVectorStore:
    """
    Wrapper for ChromaDB operations.
    """

    def __init__(self, collection_name: str = "rss_articles"):
        self.persist_dir = os.getenv(
            "RSS_VECTOR_DB_DIR", os.path.join(os.getcwd(), "chroma_db")
        )
        self.collection_name = collection_name
        self.fingerprint_path = os.path.join(
            self.persist_dir, f"{self.collection_name}_embedding_fingerprint.json"
        )
        self.client = None
        self.collection = None
        self._trending_cache = None
        self._trending_cache_time = None
        self._initialize()

    def _initialize(self):
        try:
            if chromadb is None:
                raise RuntimeError(
                    f"chromadb import failed: {CHROMADB_IMPORT_ERROR}."
                    f"{_build_chromadb_import_guidance()}"
                )
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            embedding_fn = DashScopeEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name, embedding_function=embedding_fn
            )
            self._ensure_embedding_fingerprint(embedding_fn)
            logger.info(
                f"ChromaDB initialized at {self.persist_dir}, collection: {self.collection_name}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")

    def _build_embedding_fingerprint(self, embedding_fn: DashScopeEmbeddingFunction) -> dict:
        identity = {
            "schema_version": 1,
            "collection_name": self.collection_name,
            "base_url": embedding_fn.base_url.rstrip("/"),
            "model": embedding_fn.model_name,
        }
        payload = json.dumps(identity, sort_keys=True, ensure_ascii=True)
        return {
            **identity,
            "fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }

    def _load_embedding_fingerprint(self) -> dict | None:
        if not os.path.exists(self.fingerprint_path):
            return None

        try:
            with open(self.fingerprint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(
                f"Failed to read embedding fingerprint file {self.fingerprint_path}: {e}"
            )
            return None

    def _write_embedding_fingerprint(self, fingerprint: dict) -> None:
        os.makedirs(self.persist_dir, exist_ok=True)
        with open(self.fingerprint_path, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, ensure_ascii=False, indent=2)

    def _ensure_embedding_fingerprint(
        self, embedding_fn: DashScopeEmbeddingFunction
    ) -> None:
        current = self._build_embedding_fingerprint(embedding_fn)
        existing = self._load_embedding_fingerprint()

        if not existing:
            self._write_embedding_fingerprint(current)
            return

        if existing.get("fingerprint") == current["fingerprint"]:
            return

        article_count = 0
        try:
            article_count = self.collection.count() if self.collection else 0
        except Exception as e:
            logger.warning(f"Failed to count vector store entries for fingerprint check: {e}")

        if article_count > 0:
            logger.warning(
                "Embedding fingerprint mismatch for collection '%s'. Existing vectors were "
                "built with model='%s' base_url='%s', but current config is model='%s' "
                "base_url='%s'. Rebuild the vector store before relying on semantic search.",
                self.collection_name,
                existing.get("model"),
                existing.get("base_url"),
                current.get("model"),
                current.get("base_url"),
            )
            return

        logger.info(
            "Embedding fingerprint changed for empty collection '%s'; updating metadata.",
            self.collection_name,
        )
        self._write_embedding_fingerprint(current)

    def add_article(self, article_id: str, text: str, metadata: dict = None) -> bool:
        """
        Add or update an article in the vector store.
        """
        if not self.collection:
            return False

        if not text or len(text.strip()) == 0:
            return False

        try:
            # Ensure metadata values are compatible (flat dict, primitives only usually)
            safe_metadata = {}
            if metadata:
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        safe_metadata[k] = v
                    else:
                        safe_metadata[k] = str(v)

            # Upsert
            self.collection.upsert(
                ids=[article_id], documents=[text], metadatas=[safe_metadata]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add article {article_id} to vector store: {e}")
            return False

    def search_similar(self, query: str, limit: int = 5, min_score: float = None) -> List[dict]:
        """
        Search for similar articles.
        Returns a list of dicts with id, document, metadata, and distance.

        Args:
            query: Search query text
            limit: Maximum number of results to return
            min_score: Minimum score threshold (optional filtering)
        """
        if not self.collection:
            return []

        try:
            # Increase the number of results we fetch to account for potential filtering
            fetch_limit = limit * 3 if min_score is not None else limit
            results = self.collection.query(query_texts=[query], n_results=fetch_limit)

            # Format results
            # results structure: {'ids': [['id1', 'id2']], 'documents': [['doc1', 'doc2']], ...}
            formatted_results = []
            if results["ids"]:
                ids = results["ids"][0]
                documents = results["documents"][0] if results["documents"] else []
                metadatas = results["metadatas"][0] if results["metadatas"] else []
                distances = results["distances"][0] if results["distances"] else []

                for i in range(len(ids)):
                    result_item = {
                        "id": ids[i],
                        "text": documents[i] if i < len(documents) else "",
                        "metadata": metadatas[i] if i < len(metadatas) else {},
                        "distance": distances[i] if i < len(distances) else 0.0,
                    }

                    # Apply score filtering if min_score is specified
                    if min_score is not None:
                        score = result_item["metadata"].get("score")
                        if score is not None and score < min_score:
                            continue  # Skip this result if below threshold

                    formatted_results.append(result_item)

            # Return only up to the requested limit
            return formatted_results[:limit]

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def delete_article(self, article_id: str) -> bool:
        """
        Delete an article from the vector store

        Args:
            article_id: ID of the article to delete

        Returns:
            Boolean indicating success
        """
        try:
            self.collection.delete(ids=[article_id])
            logger.debug(f"Deleted article {article_id} from vector store")
            return True
        except Exception as e:
            logger.error(
                f"Failed to delete article {article_id} from vector store: {e}"
            )
            return False

    def delete_articles(self, article_ids: List[str]) -> bool:
        """
        Delete multiple articles from the vector store

        Args:
            article_ids: List of IDs of articles to delete

        Returns:
            Boolean indicating success
        """
        try:
            self.collection.delete(ids=article_ids)
            logger.debug(f"Deleted {len(article_ids)} articles from vector store")
            return True
        except Exception as e:
            logger.error(f"Failed to delete articles from vector store: {e}")
            return False

    def clear_collection(self) -> bool:
        """
        Clear all articles from the vector store collection

        Returns:
            Boolean indicating success
        """
        try:
            # Get all IDs in the collection first
            all_items = self.collection.get(include=[])
            if all_items["ids"]:
                self.collection.delete(ids=all_items["ids"])
                logger.info(
                    f"Cleared {len(all_items['ids'])} articles from vector store"
                )
            else:
                logger.info("Vector store collection was already empty")
            return True
        except Exception as e:
            logger.error(f"Failed to clear vector store collection: {e}")
            return False

    def get_article_count(self) -> int:
        """
        Get the total number of articles in the vector store

        Returns:
            Total count of articles
        """
        try:
            count = self.collection.count()
            return count
        except Exception as e:
            logger.error(f"Failed to get article count: {e}")
            return 0

    def get_all_article_ids(self) -> List[str]:
        """
        Get all article IDs in the vector store

        Returns:
            List of all article IDs
        """
        try:
            all_items = self.collection.get(include=[])  # Get only IDs
            return all_items["ids"]
        except Exception as e:
            logger.error(f"Failed to get all article IDs: {e}")
            return []

    def get_all_articles(self) -> Dict[str, Any]:
        """
        Get all articles with their data from the vector store

        Returns:
            Dictionary containing ids, documents, and metadatas
        """
        try:
            all_items = self.collection.get(include=["documents", "metadatas"])
            return all_items
        except Exception as e:
            logger.error(f"Failed to get all articles: {e}")
            return {"ids": [], "documents": [], "metadatas": []}

    def cleanup_invalid_entries(self) -> int:
        """
        Clean up invalid entries from the vector store (e.g., with empty content)

        Returns:
            Number of entries removed
        """
        try:
            # Get all documents and their metadata
            all_items = self.collection.get(include=["documents", "metadatas", "ids"])

            invalid_ids = []
            for i, doc in enumerate(all_items["documents"]):
                # Check for empty or invalid content
                if not doc or len(doc.strip()) == 0:
                    invalid_ids.append(all_items["ids"][i])

                # Optionally check for other invalid conditions
                metadata = (
                    all_items["metadatas"][i] if i < len(all_items["metadatas"]) else {}
                )
                if (
                    not metadata.get("title") and len(doc.strip()) < 10
                ):  # Very short without title
                    if all_items["ids"][i] not in invalid_ids:
                        invalid_ids.append(all_items["ids"][i])

            if invalid_ids:
                self.collection.delete(ids=invalid_ids)
                logger.info(
                    f"Cleaned up {len(invalid_ids)} invalid entries from vector store"
                )

            return len(invalid_ids)
        except Exception as e:
            logger.error(f"Failed to clean up invalid entries: {e}")
            return 0

    def get_article_tags(self, article_id: str, text: str = None) -> List[str]:
        """
        Get tags for an article using simple keyword extraction from title and content

        Args:
            article_id: ID of the article to tag
            text: Article text to analyze (optional, will fetch from collection if not provided)

        Returns:
            List of tags for the article
        """
        try:
            if not text:
                # Get the article text from the collection
                article_data = self.collection.get(
                    ids=[article_id], include=["documents", "metadatas"]
                )
                if not article_data["documents"] or not article_data["documents"]:
                    logger.warning(f"Article {article_id} not found or has no content")
                    return []

                # Combine title and document for better tagging
                metadata = (
                    article_data["metadatas"][0] if article_data["metadatas"] else {}
                )
                title = metadata.get("title", "")
                doc = article_data["documents"][0]
                text = f"{title} {doc}"

            # Simple keyword extraction based on common terms in tech articles
            import re

            text_lower = text.lower()

            # Define common tech and topic-related keywords
            tech_keywords = [
                "ai",
                "artificial intelligence",
                "machine learning",
                "ml",
                "data science",
                "analytics",
                "big data",
                "database",
                "programming",
                "software",
                "development",
                "devops",
                "cloud",
                "aws",
                "azure",
                "gcp",
                "kubernetes",
                "docker",
                "security",
                "cybersecurity",
                "blockchain",
                "crypto",
                "web development",
                "mobile",
                "android",
                "ios",
                "algorithm",
                "research",
                "innovation",
                "digital",
                "automation",
                "robotics",
                "iot",
                "internet of things",
                "api",
                "microservices",
                "architecture",
                "design",
                "python",
                "javascript",
                "java",
                "go",
                "rust",
                "typescript",
                "startup",
                "business",
                "product",
                "management",
                "leadership",
            ]

            found_tags = set()

            # Look for keywords in the text
            for keyword in tech_keywords:
                if keyword in text_lower:
                    # Use the original case from the text if possible
                    matches = re.findall(
                        r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE
                    )
                    if matches:
                        # Take the first match to preserve original casing
                        found_tags.add(matches[0].title())

            # Extract any capitalized words that might be important
            # Look for sequences that look like proper nouns or important terms
            caps_words = re.findall(r"\b[A-Z]{2,}[a-z]*\b|\b[A-Z][a-z]{2,}\b", text)
            for word in caps_words:
                if len(word) > 2 and word.lower() not in [
                    "the",
                    "and",
                    "for",
                    "are",
                    "but",
                    "not",
                    "you",
                    "all",
                    "can",
                    "had",
                    "her",
                    "was",
                    "one",
                    "our",
                    "out",
                    "day",
                    "get",
                    "has",
                    "him",
                    "his",
                    "how",
                    "its",
                    "may",
                    "new",
                    "now",
                    "old",
                    "see",
                    "two",
                    "who",
                    "boy",
                    "did",
                    "man",
                    "men",
                    "run",
                    "too",
                    "title",
                    "content",
                ]:
                    found_tags.add(word)

            # Return up to 5 tags
            return list(found_tags)[:5]

        except Exception as e:
            logger.error(f"Failed to get tags for article {article_id}: {e}")
            return []

    def get_similar_articles_with_tags(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get similar articles with their tags

        Args:
            query: Search query
            limit: Number of results to return

        Returns:
            List of articles with their tags
        """
        try:
            results = self.search_similar(query, limit)

            # Add tags to each result
            for result in results:
                tags = self.get_article_tags(result["id"], result["text"])
                result["tags"] = tags

            return results

        except Exception as e:
            logger.error(f"Failed to get similar articles with tags: {e}")
            # Return results without tags
            return self.search_similar(query, limit)

    def discover_trending_topics(self, limit: int = 5, sample_size: int = 100, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Discover trending topics based on frequently occurring tags in recent articles

        Args:
            limit: Number of trending topics to return
            sample_size: Number of recent articles to sample for trends
            hours: Number of hours to look back for trending topics (default 24h)
        """
        try:
            from datetime import datetime, timedelta
            from rss_analyzer.cache import get_app_cache, set_app_cache

            # Check persistent cache (15 minutes TTL)
            current_time = datetime.now()
            cache_key = f"trending_{limit}_{sample_size}_{hours}"
            cached_data = get_app_cache(cache_key)
            if cached_data:
                logger.info("Returning trending topics from persistent cache")
                return cached_data

            # Get articles with metadatas
            all_articles = self.collection.get(include=["documents", "metadatas"])

            if not all_articles["ids"]:
                return []

            # Filter by time if hours is specified
            cutoff_time = (current_time - timedelta(hours=hours)).isoformat()

            items = []
            for i in range(len(all_articles["ids"])):
                metadata = all_articles["metadatas"][i] if i < len(all_articles["metadatas"]) else {}
                updated_at = metadata.get("updated_at", "")

                # Only include articles within the time window
                if updated_at >= cutoff_time:
                    items.append({
                        "id": all_articles["ids"][i],
                        "document": all_articles["documents"][i],
                        "metadata": metadata,
                        "updated_at": updated_at
                    })

            if not items:
                logger.info(f"No articles found in the last {hours} hours. Falling back to latest {sample_size} articles.")
                # Fallback to latest sample_size articles if no articles in the last 24h
                # Re-process all articles without time filter
                items = []
                for i in range(len(all_articles["ids"])):
                    metadata = all_articles["metadatas"][i] if i < len(all_articles["metadatas"]) else {}
                    items.append({
                        "id": all_articles["ids"][i],
                        "document": all_articles["documents"][i],
                        "metadata": metadata,
                        "updated_at": metadata.get("updated_at", "")
                    })
                items.sort(key=lambda x: x["updated_at"], reverse=True)
                items = items[:sample_size]
            else:
                # Sort by updated_at descending (newest first)
                items.sort(key=lambda x: x["updated_at"], reverse=True)

            # Extract tags for the results
            all_tags = []

            for item in items:
                article_id = item["id"]
                text = item["document"]
                title = item["metadata"].get("title", "")
                full_text = f"{title} {text}"

                tags = self.get_article_tags(article_id, full_text)
                all_tags.extend([tag.lower() for tag in tags])

            # Count tag frequencies
            from collections import Counter

            tag_counts = Counter(all_tags)

            # Return top tags as trending topics
            trending = []
            for tag, count in tag_counts.most_common(limit):
                trending.append(
                    {
                        "topic": tag.title(),
                        "frequency": count,
                        "percentage": round((count / len(all_tags)) * 100, 2)
                        if all_tags
                        else 0,
                    }
                )

            # Update persistent cache (15 mins TTL)
            set_app_cache(cache_key, trending, 900)

            return trending

        except Exception as e:
            logger.error(f"Failed to discover trending topics: {e}")
            return []


# Singleton instance
vector_store = ChromaVectorStore()
