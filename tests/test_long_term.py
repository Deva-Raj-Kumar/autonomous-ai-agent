"""Tests for long-term memory: storage rules, de-duplication, and retrieval scoring."""

from datetime import UTC, datetime, timedelta

import pytest

from app.database.connection import Database
from app.database.models import Memory
from app.memory.long_term import (
    LongTermMemory,
    MemoryRejected,
    as_utc,
    jaccard,
    recency_score,
    tokenize,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def db() -> Database:
    database = Database("sqlite://")
    database.create_tables()
    return database


@pytest.fixture
def memory(db: Database) -> LongTermMemory:
    return LongTermMemory(db)


# ------------------------------------------------------------ pure helpers
def test_tokenize_drops_stopwords_and_plurals() -> None:
    assert tokenize("The user knows Python and SQL jobs") == {"know", "python", "sql", "job"}


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert jaccard(set(), {"a"}) == 0.0


def test_recency_halves_every_30_days() -> None:
    now = datetime.now(UTC)
    assert recency_score(now, now) == pytest.approx(1.0)
    assert recency_score(now - timedelta(days=30), now) == pytest.approx(0.5)


def test_naive_datetimes_are_treated_as_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0)  # what SQLite gives back
    assert as_utc(naive).tzinfo is UTC
    # Would raise TypeError without as_utc: can't subtract naive from aware.
    assert recency_score(naive, datetime(2026, 1, 31, 12, 0, tzinfo=UTC)) == pytest.approx(0.5)


# ------------------------------------------------------------------ writes
async def test_add_and_list(memory: LongTermMemory) -> None:
    record, created = await memory.add("User lives in Hyderabad.", category="profile", importance=4)

    assert created and record.id == 1
    assert [m.content for m in await memory.list_memories()] == ["User lives in Hyderabad."]


async def test_near_duplicate_is_refreshed_not_added(memory: LongTermMemory) -> None:
    await memory.add("User knows Python and SQL.", importance=3)
    record, created = await memory.add("user knows python and SQL", importance=5)

    assert created is False
    assert record.importance == 5  # importance raised to the max of both
    assert len(await memory.list_memories()) == 1


async def test_different_facts_are_both_kept(memory: LongTermMemory) -> None:
    await memory.add("User lives in Pune.")
    await memory.add("User lives in Hyderabad.")

    assert len(await memory.list_memories()) == 2  # conflicts are the LLM's job, not dedupe's


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("   ", "empty"),
        ("x" * 301, "longer than"),
        ("User's password: hunter2", "secret"),
        ("User key sk-abcdefghijklmnopqrstuvwxyz123456", "secret"),
    ],
)
async def test_invalid_content_is_rejected(memory: LongTermMemory, content: str, reason: str) -> None:
    with pytest.raises(MemoryRejected, match=reason):
        await memory.add(content)


async def test_importance_is_clamped(memory: LongTermMemory) -> None:
    record, _ = await memory.add("User likes chai.", importance=99)
    assert record.importance == 5


async def test_update_and_delete(memory: LongTermMemory) -> None:
    record, _ = await memory.add("User lives in Pune.")

    updated = await memory.update(record.id, "User lives in Hyderabad.", importance=4)
    assert updated.content == "User lives in Hyderabad." and updated.importance == 4

    assert await memory.delete(record.id) is True
    assert await memory.get(record.id) is None
    assert await memory.update(999, "anything") is None


# --------------------------------------------------------------- retrieval
async def test_search_ranks_relevant_memories_first(memory: LongTermMemory) -> None:
    await memory.add("User knows Python and SQL.", category="skill", importance=3)
    await memory.add("User likes cricket.", category="preference", importance=2)
    await memory.add("User wants a Python backend job.", category="goal", importance=5)

    results = await memory.search("python job openings")

    assert [r.memory.content for r in results] == [
        "User wants a Python backend job.",  # 2 of 3 query words + high importance
        "User knows Python and SQL.",
    ]
    assert all(r.relevance > 0 for r in results)  # cricket is not relevant: excluded


async def test_min_relevance_zero_includes_everything(memory: LongTermMemory) -> None:
    await memory.add("User lives in Pune.")

    assert await memory.search("I moved to Hyderabad") == []
    assert len(await memory.search("I moved to Hyderabad", min_relevance=0.0)) == 1


async def test_empty_query_ranks_by_importance(memory: LongTermMemory) -> None:
    await memory.add("User likes chai.", importance=1)
    await memory.add("User is named Ravi.", importance=5)

    results = await memory.search("")

    assert results[0].memory.content == "User is named Ravi."


async def test_recency_breaks_ties(memory: LongTermMemory, db: Database) -> None:
    old, _ = await memory.add("User studies machine learning.", importance=3)
    await memory.add("User studies deep learning.", importance=3)
    with db.session() as s:  # make the first memory 90 days old
        s.get(Memory, old.id).updated_at = datetime.now(UTC) - timedelta(days=90)

    results = await memory.search("studies learning", mark_accessed=False)

    assert results[0].memory.content == "User studies deep learning."


async def test_search_marks_memories_as_accessed(memory: LongTermMemory) -> None:
    record, _ = await memory.add("User knows Docker.")

    await memory.search("docker")
    await memory.search("docker")

    assert (await memory.get(record.id)).access_count == 2


# ------------------------------------------------- semantic search (Phase 6)
@pytest.fixture
def index():
    """A create_autospec mock of the semantic index, using the REAL LocalEmbedder's
    thresholds for relevance() (pure math, no model is loaded)."""
    from unittest.mock import create_autospec

    from app.memory.vector_store import MemoryVectorIndex
    from app.rag.embeddings import LocalEmbedder

    mock = create_autospec(MemoryVectorIndex, instance=True)
    mock.embedder = LocalEmbedder()
    mock.similarities.return_value = {}
    return mock


async def test_semantic_match_without_shared_words(db: Database, index) -> None:
    memory = LongTermMemory(db, index)
    hyderabad, _ = await memory.add("User lives in Hyderabad.", importance=3)
    await memory.add("User likes cricket.", importance=3)
    index.similarities.return_value = {hyderabad.id: 0.45}  # meaning match; cricket isn't close

    results = await memory.search("Which city should I job-hunt in?")

    assert [r.memory.content for r in results] == ["User lives in Hyderabad."]
    assert results[0].relevance == pytest.approx(local_relevance(0.45), abs=1e-4)  # stored rounded to 4 dp
    index.similarities.assert_awaited_once_with("Which city should I job-hunt in?")


def local_relevance(similarity: float) -> float:
    from app.rag.embeddings import LocalEmbedder

    return LocalEmbedder().relevance(similarity)


async def test_index_follows_database_writes(db: Database, index) -> None:
    memory = LongTermMemory(db, index)

    record, _ = await memory.add("User knows Docker.")
    index.upsert.assert_awaited_once_with(record.id, "User knows Docker.")

    await memory.add("user knows docker")  # near-duplicate: refreshed, not re-embedded
    assert index.upsert.await_count == 1

    await memory.update(record.id, "User knows Docker and Kubernetes.")
    index.upsert.assert_awaited_with(record.id, "User knows Docker and Kubernetes.")

    await memory.delete(record.id)
    index.delete.assert_awaited_once_with(record.id)


async def test_index_failure_never_loses_a_memory(db: Database, index) -> None:
    index.upsert.side_effect = RuntimeError("embedding model crashed")
    index.similarities.side_effect = RuntimeError("chroma down")
    memory = LongTermMemory(db, index)

    record, created = await memory.add("User knows Python.")  # still saved in the DB
    results = await memory.search("python")  # falls back to keyword search

    assert created and [r.memory.id for r in results] == [record.id]


async def test_sync_index_sends_all_memories(db: Database, index) -> None:
    memory = LongTermMemory(db, index)
    a, _ = await memory.add("User likes chai.")
    b, _ = await memory.add("User lives in Pune.")
    index.sync.return_value = 2

    assert await memory.sync_index() == 2
    index.sync.assert_awaited_once_with({a.id: "User likes chai.", b.id: "User lives in Pune."})
@pytest.mark.anyio
async def test_rows_written_by_other_tools_with_nulls_do_not_break_listing() -> None:
    from app.database.connection import Database
    from app.database.models import Memory

    database = Database("sqlite://")
    database.create_tables()
    with database.session() as s:  # only the NOT NULL columns, like a hand-written INSERT
        s.add(Memory(user_id=database.default_user_id(), content=None, category=None, source=None,
                     created_at=None, updated_at=None))
    memory = LongTermMemory(database)

    listed = await memory.list_memories()
    found = await memory.search("")

    assert (listed[0].content, listed[0].category, listed[0].source) == ("", "other", "unknown")
    assert len(found) == 1
    database.dispose()
