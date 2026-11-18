"""Long-term memory: lasting facts about the user, stored in the database.

RETRIEVAL. When the user says something, which memories should go into the prompt?
We score every memory on three signals (the idea comes from the "Generative Agents"
paper, Park et al. 2023):

    score = 0.60 * relevance   how many of the query's words the memory contains
          + 0.25 * importance  1-5, set when stored (core identity > trivia)
          + 0.15 * recency     halves every 30 days since last update/use

Relevance here is KEYWORD overlap, which is simple and explainable but misses
synonyms ("job" vs "career"). Phase 6 adds embeddings for semantic relevance, behind
this same search() method, so callers won't need to change.

WRITES are protected: secrets are refused, content length is limited, and an almost
identical memory is updated instead of duplicated.
"""

import asyncio
import logging
import math
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.database.connection import Database
from app.database.models import Memory
from app.memory.schemas import MemoryRecord, ScoredMemory
from app.safety.secrets import contains_secret

if TYPE_CHECKING:  # imported only for type hints: avoids a circular import at runtime
    from app.memory.vector_store import MemoryVectorIndex

logger = logging.getLogger(__name__)

MAX_MEMORY_CHARS = 300
RECENCY_HALF_LIFE_DAYS = 30.0
DUPLICATE_THRESHOLD = 0.8  # word-overlap (Jaccard) at or above this = same fact
WEIGHTS = {"relevance": 0.60, "importance": 0.25, "recency": 0.15}

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have i in is it its me my of on or our that the "
    "their this to was were will with you your user am do does did what which who how".split()
)


class MemoryRejected(ValueError):
    """The content can't be stored (secret, empty, too long)."""


def tokenize(text: str) -> set[str]:
    """Lowercase words without stopwords, with a light plural fix ('jobs' -> 'job')."""
    words = re.findall(r"[a-z0-9+#]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    """Overlap of two word sets: |A ∩ B| / |A ∪ B|, from 0 (nothing shared) to 1 (identical)."""
    return len(a & b) / len(a | b) if a and b else 0.0


def as_utc(moment: datetime) -> datetime:
    """SQLite drops timezone info, so a value read back is 'naive'. Treat naive as UTC.

    Without this, subtracting naive from aware datetimes raises TypeError.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def recency_score(updated_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - as_utc(updated_at)).total_seconds() / 86_400)
    return math.pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS)  # 1.0 today, 0.5 after 30 days


def validate_content(content: str) -> str:
    content = " ".join(content.split())  # collapse whitespace and newlines
    if not content:
        raise MemoryRejected("Memory content is empty.")
    if len(content) > MAX_MEMORY_CHARS:
        raise MemoryRejected(f"Memory is longer than {MAX_MEMORY_CHARS} characters.")
    if contains_secret(content):
        raise MemoryRejected("Memory looks like it contains a secret; refusing to store it.")
    return content


class LongTermMemory:
    def __init__(self, database: Database, index: "MemoryVectorIndex | None" = None) -> None:
        self._db = database
        # Optional semantic index (Phase 6). The database stays the source of truth;
        # if the index is missing or fails, search falls back to keywords only.
        self._index = index

    # --------------------------------------------------------------- public API
    async def add(
        self, content: str, *, category: str = "other", importance: int = 3, source: str = "manual"
    ) -> tuple[MemoryRecord, bool]:
        """Store a fact. Returns (record, created). created=False means an almost
        identical memory already existed, and it was refreshed instead."""
        content = validate_content(content)
        importance = min(5, max(1, importance))
        record, created = await asyncio.to_thread(self._add, content, category, importance, source)
        if created:
            await self._index_call("upsert", record.id, record.content)
        return record, created

    async def update(
        self, memory_id: int, content: str, *, category: str | None = None, importance: int | None = None
    ) -> MemoryRecord | None:
        content = validate_content(content)
        record = await asyncio.to_thread(self._update, memory_id, content, category, importance)
        if record is not None:
            await self._index_call("upsert", record.id, record.content)
        return record

    async def delete(self, memory_id: int) -> bool:
        deleted = await asyncio.to_thread(self._delete, memory_id)
        if deleted:
            await self._index_call("delete", memory_id)
        return deleted

    async def sync_index(self) -> int:
        """Embed memories that aren't in the vector index yet (e.g. created before Phase 6)."""
        if self._index is None:
            return 0
        # A startup job for the whole server, not for one user: it embeds EVERY user's
        # memories. (Safe: searches only score memories the current user owns.)
        memories = await asyncio.to_thread(self._all_memory_texts)
        return await self._index.sync(memories)

    def _all_memory_texts(self) -> dict[int, str]:
        with self._db.session() as s:
            return {m_id: text or "" for m_id, text in s.execute(select(Memory.id, Memory.content))}

    async def _index_call(self, method: str, *args) -> None:
        """Keep the index in step with the database, without ever failing the DB write."""
        if self._index is None:
            return
        try:
            await getattr(self._index, method)(*args)
        except Exception as exc:  # embedding/Chroma problems must not lose the memory
            logger.warning("Memory index %s failed (keyword search still works): %s", method, exc)

    async def _semantic_relevance(self, query: str) -> dict[int, float]:
        """memory_id -> 0..1 relevance by meaning, using the embedder's own thresholds."""
        if self._index is None or not query.strip():
            return {}
        try:
            raw = await self._index.similarities(query)
        except Exception as exc:
            logger.warning("Semantic memory search failed, using keywords only: %s", exc)
            return {}
        return {mid: self._index.embedder.relevance(sim) for mid, sim in raw.items()}

    async def get(self, memory_id: int) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get, memory_id)

    # Not named `list`: a method called `list` would shadow the built-in list type
    # in every annotation below it inside this class.
    async def list_memories(self, *, category: str | None = None, limit: int = 100) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._list_memories, category, limit)

    async def search(
        self, query: str, *, limit: int = 5, min_relevance: float = 0.01, mark_accessed: bool = True
    ) -> list[ScoredMemory]:
        """Most useful memories for `query`, best first. An empty query ranks by
        importance and recency only (useful for "what do you know about me?").

        relevance = max(keyword relevance, semantic relevance): a memory counts as
        relevant if it shares words with the query OR means something similar.
        """
        semantic = await self._semantic_relevance(query)
        return await asyncio.to_thread(self._search, query, limit, min_relevance, mark_accessed, semantic)

    # ---------------------------------------------------- sync implementation
    # Every query is scoped to ONE user: the logged-in user (API) or the local user (CLI),
    # so memories can never leak between accounts.
    def _mine(self):
        return select(Memory).where(Memory.user_id == self._db.current_user_id())

    def _owned(self, s, memory_id: int) -> Memory | None:
        memory = s.get(Memory, memory_id)
        return memory if memory is not None and memory.user_id == self._db.current_user_id() else None

    def _add(self, content: str, category: str, importance: int, source: str) -> tuple[MemoryRecord, bool]:
        new_words = tokenize(content)
        now = datetime.now(UTC)
        user_id = self._db.current_user_id()
        with self._db.session() as s:
            for existing in s.scalars(self._mine()).all():
                if jaccard(new_words, tokenize(existing.content or "")) >= DUPLICATE_THRESHOLD:
                    existing.updated_at = now  # refresh: the user said it again
                    existing.importance = max(existing.importance, importance)
                    return MemoryRecord.model_validate(existing), False
            memory = Memory(
                user_id=user_id, content=content, category=category, importance=importance, source=source,
                created_at=now, updated_at=now,
            )
            s.add(memory)
            s.flush()  # assigns memory.id
            return MemoryRecord.model_validate(memory), True

    def _update(self, memory_id: int, content: str, category: str | None, importance: int | None) -> MemoryRecord | None:
        with self._db.session() as s:
            memory = self._owned(s, memory_id)
            if memory is None:
                return None
            memory.content = content
            if category:
                memory.category = category
            if importance is not None:
                memory.importance = min(5, max(1, importance))
            memory.updated_at = datetime.now(UTC)
            return MemoryRecord.model_validate(memory)

    def _delete(self, memory_id: int) -> bool:
        user_id = self._db.current_user_id()
        with self._db.session() as s:
            result = s.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
            return result.rowcount > 0

    def _get(self, memory_id: int) -> MemoryRecord | None:
        with self._db.session() as s:
            memory = self._owned(s, memory_id)
            return MemoryRecord.model_validate(memory) if memory else None

    def _list_memories(self, category: str | None, limit: int) -> list[MemoryRecord]:
        with self._db.session() as s:
            query = self._mine().order_by(Memory.importance.desc(), Memory.updated_at.desc(), Memory.id.desc())
            if category:
                query = query.where(Memory.category == category)
            return [MemoryRecord.model_validate(m) for m in s.scalars(query.limit(limit)).all()]

    def _search(
        self, query: str, limit: int, min_relevance: float, mark_accessed: bool,
        semantic: dict[int, float] | None = None,
    ) -> list[ScoredMemory]:
        query_words = tokenize(query)
        semantic = semantic or {}
        now = datetime.now(UTC)
        with self._db.session() as s:
            # A personal agent has hundreds of memories, so scoring them all in Python
            # is fine. At scale you'd pre-filter in the DB (full-text index / pgvector).
            memories = s.scalars(self._mine()).all()
            scored: list[tuple[float, float, float, Memory]] = []
            for memory in memories:
                words = tokenize(memory.content or "")  # the column allows NULL in your schema
                if query_words:
                    keyword = len(query_words & words) / len(query_words)
                    relevance = max(keyword, semantic.get(memory.id, 0.0))
                    if relevance < min_relevance:
                        continue  # below the caller's relevance threshold: skip
                else:
                    relevance = 0.0
                last_seen = memory.last_accessed_at or memory.updated_at or memory.created_at or now
                recency = recency_score(last_seen, now)
                score = (
                    WEIGHTS["relevance"] * relevance
                    + WEIGHTS["importance"] * memory.importance / 5
                    + WEIGHTS["recency"] * recency
                )
                scored.append((score, relevance, recency, memory))

            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[:limit]
            if mark_accessed:  # using a memory keeps it "fresh" (affects future recency)
                for _, _, _, memory in top:
                    memory.last_accessed_at = now
                    memory.access_count += 1
            return [
                ScoredMemory(
                    memory=MemoryRecord.model_validate(m),
                    score=round(score, 4), relevance=round(rel, 4), recency=round(rec, 4),
                )
                for score, rel, rec, m in top
            ]
