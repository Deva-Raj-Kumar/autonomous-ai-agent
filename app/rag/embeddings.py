"""Embeddings: turn text into a vector (a list of numbers) that captures its MEANING.

Texts with similar meaning get vectors pointing in similar directions, so we compare
them with cosine similarity (1.0 = same direction, about 0 = unrelated).

Two interchangeable embedders (same interface, chosen by EMBEDDING_PROVIDER):
  - LocalEmbedder:  all-MiniLM-L6-v2 (a Hugging Face model) run with ONNX on your CPU.
                    Free, private, offline after a one-time ~80 MB download. 384 numbers.
  - GeminiEmbedder: Google's embedding API. Uses your key and quota.

IMPORTANT: similarity scores are NOT comparable between models. Measured in this project:
"Which city should I look for jobs in?" vs "User lives in Hyderabad."
    MiniLM: 0.25 (unrelated text: ~0.0)    Gemini: 0.58 (unrelated text: ~0.55)
So each embedder carries its OWN thresholds (similarity_floor / similarity_strong),
and vectors from different models are never mixed in one collection.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import SecretStr

from app.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Embedding failed (model download, API error, quota...)."""


class Embedder(ABC):
    """Common interface for all embedding models."""

    name: str  # unique per model + settings; used in collection names
    similarity_floor: float  # below this, texts are treated as unrelated
    similarity_strong: float  # at or above this, a match counts as strong (relevance 1.0)
    batch_size: ClassVar[int] = 64

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectors for texts that will be STORED (chunks, memories)."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Vector for a SEARCH query. Some models embed queries differently from documents."""

    def relevance(self, similarity: float) -> float:
        """Map this model's raw similarity onto 0..1, using its own thresholds."""
        span = self.similarity_strong - self.similarity_floor
        return max(0.0, min(1.0, (similarity - self.similarity_floor) / span))


class LocalEmbedder(Embedder):
    name = "local-minilm-l6-v2"
    # Tuned on this project's sample documents: off-topic questions ("capital of France",
    # "bake a cake") scored <= 0.149; vague but relevant ones ("compare the two
    # opportunities") scored >= 0.161. 0.20 wrongly dropped real matches. The margin is
    # small, so re-measure on YOUR documents (python -m app.cli kb search ...).
    similarity_floor = 0.16
    similarity_strong = 0.60

    def __init__(self) -> None:
        self._function = None  # created on first use: loading the model takes ~1-30 s

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self._function is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            logger.info("Loading local embedding model (first time downloads ~80 MB)...")
            self._function = DefaultEmbeddingFunction()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):  # batches keep memory use flat
            batch = texts[start : start + self.batch_size]
            vectors.extend([float(x) for x in v] for v in self._function(batch))  # numpy -> floats
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            # The model runs on the CPU and blocks, so it goes to a worker thread.
            return await asyncio.to_thread(self._embed_sync, texts)
        except Exception as exc:
            raise EmbeddingError(f"Local embedding failed: {type(exc).__name__}: {exc}") from exc

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


class GeminiEmbedder(Embedder):
    similarity_floor = 0.50
    similarity_strong = 0.80
    batch_size = 100  # the API accepts up to 100 texts per request

    def __init__(self, api_key: SecretStr, model: str, dimensions: int, client=None) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._client = client  # tests inject a mock client
        self.name = f"gemini-{model}-{dimensions}"

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key.get_secret_value())
        return self._client

    async def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self._dimensions)
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = await self._get_client().aio.models.embed_content(
                    model=self._model, contents=batch, config=config
                )
                if len(response.embeddings) != len(batch):  # defensive: seen with some models
                    raise EmbeddingError("API returned a different number of vectors than texts.")
                vectors.extend(list(e.values) for e in response.embeddings)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Gemini embedding failed: {type(exc).__name__}: {exc}") from exc
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # task_type tells Gemini how the vector will be used, which improves retrieval.
        return await self._embed(texts, "RETRIEVAL_DOCUMENT") if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]


def make_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "gemini":
        if settings.google_api_key is None:
            raise ValueError("EMBEDDING_PROVIDER=gemini needs GOOGLE_API_KEY.")
        return GeminiEmbedder(
            settings.google_api_key,
            settings.gemini_embedding_model,
            settings.gemini_embedding_dimensions,
        )
    return LocalEmbedder()
