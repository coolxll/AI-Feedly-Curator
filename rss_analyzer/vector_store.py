import os
import logging
from typing import List, Dict, Any
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from openai import OpenAI

logger = logging.getLogger(__name__)


class DashScopeEmbeddingFunction(EmbeddingFunction):
    """
    Custom EmbeddingFunction for ChromaDB using Aliyun DashScope via OpenAI SDK.
    """

    def __init__(self, model_name: str = "text-embedding-v3"):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            logger.warning("DASHSCOPE_API_KEY not found in environment variables.")

        # Use provided base URL or default to DashScope compatible endpoint
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model_name = model_name
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
        self.client = None
        self.collection = None
        self._initialize()

    def _initialize(self):
        try:
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            embedding_fn = DashScopeEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name, embedding_function=embedding_fn
            )
            logger.info(
                f"ChromaDB initialized at {self.persist_dir}, collection: {self.collection_name}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")

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

    def search_similar(self, query: str, limit: int = 5) -> List[dict]:
        """
        Search for similar articles.
        Returns a list of dicts with id, document, metadata, and distance.
        """
        if not self.collection:
            return []

        try:
            results = self.collection.query(query_texts=[query], n_results=limit)

            # Format results
            # results structure: {'ids': [['id1', 'id2']], 'documents': [['doc1', 'doc2']], ...}
            formatted_results = []
            if results["ids"]:
                ids = results["ids"][0]
                documents = results["documents"][0] if results["documents"] else []
                metadatas = results["metadatas"][0] if results["metadatas"] else []
                distances = results["distances"][0] if results["distances"] else []

                for i in range(len(ids)):
                    formatted_results.append(
                        {
                            "id": ids[i],
                            "text": documents[i] if i < len(documents) else "",
                            "metadata": metadatas[i] if i < len(metadatas) else {},
                            "distance": distances[i] if i < len(distances) else 0.0,
                        }
                    )

            return formatted_results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

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
                article_data = self.collection.get(ids=[article_id], include=['documents', 'metadatas'])
                if not article_data['documents'] or not article_data['documents']:
                    logger.warning(f"Article {article_id} not found or has no content")
                    return []

                # Combine title and document for better tagging
                metadata = article_data['metadatas'][0] if article_data['metadatas'] else {}
                title = metadata.get('title', '')
                doc = article_data['documents'][0]
                text = f"{title} {doc}"

            # Simple keyword extraction based on common terms in tech articles
            import re

            text_lower = text.lower()

            # Define common tech and topic-related keywords
            tech_keywords = [
                'ai', 'artificial intelligence', 'machine learning', 'ml',
                'data science', 'analytics', 'big data', 'database',
                'programming', 'software', 'development', 'devops',
                'cloud', 'aws', 'azure', 'gcp', 'kubernetes', 'docker',
                'security', 'cybersecurity', 'blockchain', 'crypto',
                'web development', 'mobile', 'android', 'ios',
                'algorithm', 'research', 'innovation', 'digital',
                'automation', 'robotics', 'iot', 'internet of things',
                'api', 'microservices', 'architecture', 'design',
                'python', 'javascript', 'java', 'go', 'rust', 'typescript',
                'startup', 'business', 'product', 'management', 'leadership'
            ]

            found_tags = set()

            # Look for keywords in the text
            for keyword in tech_keywords:
                if keyword in text_lower:
                    # Use the original case from the text if possible
                    matches = re.findall(r'\b' + re.escape(keyword) + r'\b', text, re.IGNORECASE)
                    if matches:
                        # Take the first match to preserve original casing
                        found_tags.add(matches[0].title())

            # Extract any capitalized words that might be important
            # Look for sequences that look like proper nouns or important terms
            caps_words = re.findall(r'\b[A-Z]{2,}[a-z]*\b|\b[A-Z][a-z]{2,}\b', text)
            for word in caps_words:
                if len(word) > 2 and word.lower() not in ['the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'man', 'men', 'run', 'too']:
                    found_tags.add(word)

            # Return up to 5 tags
            return list(found_tags)[:5]

        except Exception as e:
            logger.error(f"Failed to get tags for article {article_id}: {e}")
            return []

    def get_similar_articles_with_tags(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
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
                tags = self.get_article_tags(result['id'], result['text'])
                result['tags'] = tags

            return results

        except Exception as e:
            logger.error(f"Failed to get similar articles with tags: {e}")
            # Return results without tags
            return self.search_similar(query, limit)

    def discover_trending_topics(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Discover trending topics based on frequently occurring tags in recent articles

        Args:
            limit: Number of trending topics to return

        Returns:
            List of trending topics with frequency
        """
        try:
            # Get all articles from the collection
            all_articles = self.collection.get(include=['documents', 'metadatas'])

            if not all_articles['ids']:
                return []

            # Extract tags for all articles (or a sample if too many)
            all_tags = []
            article_count = len(all_articles['ids'])
            sample_size = min(20, article_count)  # Don't process too many articles

            for i in range(sample_size):
                if i < len(all_articles['ids']):
                    article_id = all_articles['ids'][i]
                    text = all_articles['documents'][i]
                    metadata = all_articles['metadatas'][i] if i < len(all_articles['metadatas']) else {}

                    # Combine title and content for better tagging
                    title = metadata.get('title', '')
                    full_text = f"{title} {text}"

                    tags = self.get_article_tags(article_id, full_text)
                    all_tags.extend([tag.lower() for tag in tags])

            # Count tag frequencies
            from collections import Counter
            tag_counts = Counter(all_tags)

            # Return top tags as trending topics
            trending = []
            for tag, count in tag_counts.most_common(limit):
                trending.append({
                    "topic": tag.title(),
                    "frequency": count,
                    "percentage": round((count / len(all_tags)) * 100, 2) if all_tags else 0
                })

            return trending

        except Exception as e:
            logger.error(f"Failed to discover trending topics: {e}")
            return []


# Singleton instance
vector_store = ChromaVectorStore()
