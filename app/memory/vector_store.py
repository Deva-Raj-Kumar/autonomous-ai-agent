"""Vector store: ChromaDB wrapper shared by the RAG knowledge base and semantic memory.

ChromaDB stores (id, vector, text, metadata) and finds the vectors closest to a query
vector very fast (an HNSW index). We give it our OWN vectors (from app/rag/embeddings.py)
so the embedding model stays swappable.

Collections are named "<base>__<embedder name>", for example
"documents__local-minilm-l6-v2". Vectors from different models have different sizes and
meanings and must never be mixed. Switching models simply uses a fresh collection.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

# Every client in one process must use the SAME settings (a ChromaDB rule).
_CHROMA_SETTINGS = ChromaSettings(anonymized_telemetry=False)


def make_chroma_client(path: Path | None = None) -> chromadb.ClientAPI:
    """Persistent client (saved to disk) for the app; in-memory when path is None (tests)."""
    if path is None:
        return chromadb.EphemeralClient(settings=_CHROMA_SETTINGS)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=_CHROMA_SETTINGS)


@dataclass
class VectorHit:
    id: str
    text: str
    metadata: dict[str, Any]
    similarity: float  # cosine similarity: 1.0 = identical direction


class VectorStore:
    def __init__(self, client: chromadb.ClientAPI, embedder: Embedder) -> None:
        self._client = client
        self.embedder = embedder

    def _collection(self, base: str):
        return self._client.get_or_create_collection(
            name=f"{base}__{self.embedder.name}",
            configuration={"hnsw": {"space": "cosine"}},  # distance = 1 - cosine similarity
            embedding_function=None,  # we always pass our own vectors
            metadata={"embedder": self.embedder.name},
        )

    async def upsert(
        self, base: str, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]]
    ) -> None:
        """Embed `texts` and insert or replace them (same id = replace)."""
        if not ids:
            return
        vectors = await self.embedder.embed_documents(texts)
        await asyncio.to_thread(
            self._collection(base).upsert,
            ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas,
        )

    async def query(
        self, base: str, text: str, n_results: int, where: dict[str, Any] | None = None
    ) -> list[VectorHit]:
        """The `n_results` stored texts most similar in meaning to `text`, best first."""
        collection = self._collection(base)
        total = await asyncio.to_thread(collection.count)
        if total == 0:
            return []
        vector = await self.embedder.embed_query(text)
        result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[vector],
            n_results=min(n_results, total),  # never ask for more than exist
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            VectorHit(id=i, text=doc, metadata=meta or {}, similarity=round(1.0 - dist, 4))
            for i, doc, meta, dist in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0],
                strict=True,  # mismatched lists from Chroma must fail loudly, not truncate
            )
        ]

    async def get(self, base: str, where: dict[str, Any] | None = None) -> list[tuple[str, dict[str, Any]]]:
        """(id, metadata) pairs, optionally filtered. No vectors or texts: cheap."""
        result = await asyncio.to_thread(self._collection(base).get, where=where, include=["metadatas"])
        return list(zip(result["ids"], [m or {} for m in result["metadatas"]], strict=True))

    async def delete(self, base: str, *, ids: list[str] | None = None, where: dict[str, Any] | None = None) -> None:
        if ids is None and where is None:
            raise ValueError("Refusing to delete without ids or a filter.")  # no accidental wipe
        await asyncio.to_thread(self._collection(base).delete, ids=ids, where=where)

    async def count(self, base: str) -> int:
        return await asyncio.to_thread(self._collection(base).count)


class MemoryVectorIndex:
    """Embeddings of long-term memories, so recall can match by meaning.

    The database (app/memory/long_term.py) stays the source of truth; this index is a
    search helper. If it fails, memory falls back to keyword search.
    """

    def __init__(self, store: VectorStore, collection: str = "memories") -> None:
        self._store = store
        self._collection = collection

    @property
    def embedder(self) -> Embedder:
        return self._store.embedder

    async def upsert(self, memory_id: int, content: str) -> None:
        await self._store.upsert(self._collection, [str(memory_id)], [content], [{"memory_id": memory_id}])

    async def delete(self, memory_id: int) -> None:
        await self._store.delete(self._collection, ids=[str(memory_id)])

    async def similarities(self, query: str, limit: int = 50) -> dict[int, float]:
        """memory_id -> raw cosine similarity, for the `limit` closest memories."""
        hits = await self._store.query(self._collection, query, n_results=limit)
        return {int(h.id): h.similarity for h in hits}

    async def sync(self, memories: dict[int, str]) -> int:
        """Make the index match the database: add missing memories, remove deleted ones.
        Returns how many were added. Run at startup (memories from before Phase 6)."""
        indexed = {int(i) for i, _ in await self._store.get(self._collection)}
        missing = {mid: text for mid, text in memories.items() if mid not in indexed}
        stale = [str(mid) for mid in indexed - memories.keys()]
        if stale:
            await self._store.delete(self._collection, ids=stale)
        if missing:
            await self._store.upsert(
                self._collection,
                [str(m) for m in missing],
                list(missing.values()),
                [{"memory_id": m} for m in missing],
            )
        return len(missing)


def build_vector_store(settings) -> VectorStore:
    """Persistent ChromaDB in CHROMA_DIR + the embedder chosen in settings."""
    from app.rag.embeddings import make_embedder

    return VectorStore(make_chroma_client(settings.chroma_dir), make_embedder(settings))
