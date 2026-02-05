import os
import logging
from typing import List
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
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model_name = model_name
        self.client = None

        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )

    def __call__(self, input: Documents) -> Embeddings:
        if not self.client:
            logger.error("Cannot generate embeddings: OpenAI client not initialized (missing API key).")
            return []

        try:
            # Clean inputs - replace newlines to potentially improve performance/accuracy
            # though text-embedding-v3 handles them reasonably well.
            cleaned_input = [text.replace("\n", " ") for text in input]

            response = self.client.embeddings.create(
                input=cleaned_input,
                model=self.model_name
            )

            # OpenAI SDK returns a list of embedding objects.
            # We need to ensure they are sorted by index (usually are) and extract the vector.
            embeddings = [data.embedding for data in response.data]
            return embeddings

        except Exception as e:
            logger.error(f"Failed to generate embeddings via OpenAI SDK: {e}")
            return []

class ChromaVectorStore:
    """
    Wrapper for ChromaDB operations.
    """
    def __init__(self, collection_name: str = "rss_articles"):
        self.persist_dir = os.getenv("RSS_VECTOR_DB_DIR", os.path.join(os.getcwd(), "chroma_db"))
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self._initialize()

    def _initialize(self):
        try:
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            embedding_fn = DashScopeEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embedding_fn
            )
            logger.info(f"ChromaDB initialized at {self.persist_dir}, collection: {self.collection_name}")
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
                ids=[article_id],
                documents=[text],
                metadatas=[safe_metadata]
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
            results = self.collection.query(
                query_texts=[query],
                n_results=limit
            )

            # Format results
            # results structure: {'ids': [['id1', 'id2']], 'documents': [['doc1', 'doc2']], ...}
            formatted_results = []
            if results['ids']:
                ids = results['ids'][0]
                documents = results['documents'][0] if results['documents'] else []
                metadatas = results['metadatas'][0] if results['metadatas'] else []
                distances = results['distances'][0] if results['distances'] else []

                for i in range(len(ids)):
                    formatted_results.append({
                        "id": ids[i],
                        "text": documents[i] if i < len(documents) else "",
                        "metadata": metadatas[i] if i < len(metadatas) else {},
                        "distance": distances[i] if i < len(distances) else 0.0
                    })

            return formatted_results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

# Singleton instance
vector_store = ChromaVectorStore()
