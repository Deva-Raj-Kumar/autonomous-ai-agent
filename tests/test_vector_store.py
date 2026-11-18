"""VectorStore and MemoryVectorIndex tests: real in-memory ChromaDB + a mocked embedder."""

import uuid

import pytest

from app.memory.vector_store import MemoryVectorIndex, VectorStore, make_chroma_client
from tests.helpers import make_embedder_mock

pytestmark = pytest.mark.anyio


@pytest.fixture
def base() -> str:
    """Unique collection name per test: in-memory Chroma clients share state in a process."""
    return f"test_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def store() -> VectorStore:
    return VectorStore(make_chroma_client(None), make_embedder_mock())


async def test_upsert_then_query_returns_most_similar_first(store: VectorStore, base: str) -> None:
    await store.upsert(
        base,
        ["a", "b", "c"],
        ["python sql developer", "cricket match tonight", "python backend developer jobs"],
        [{"n": 1}, {"n": 2}, {"n": 3}],
    )

    hits = await store.query(base, "python developer jobs", n_results=3)

    assert [h.id for h in hits][:2] == ["c", "a"]
    assert hits[0].similarity > hits[-1].similarity
    assert all(0.0 <= h.similarity <= 1.0 for h in hits)
    store.embedder.embed_documents.assert_awaited_once()
    store.embedder.embed_query.assert_awaited_once_with("python developer jobs")


async def test_collection_name_includes_the_embedder(store: VectorStore, base: str) -> None:
    await store.upsert(base, ["a"], ["text"], [{"n": 1}])

    names = {c.name for c in store._client.list_collections()}

    assert f"{base}__fake-bow" in names  # a different model would get a different collection


async def test_query_on_empty_collection_skips_embedding(store: VectorStore, base: str) -> None:
    assert await store.query(base, "anything", n_results=5) == []
    store.embedder.embed_query.assert_not_awaited()  # no wasted embedding call


async def test_asking_for_more_results_than_exist(store: VectorStore, base: str) -> None:
    await store.upsert(base, ["a"], ["only one"], [{"n": 1}])

    assert len(await store.query(base, "only", n_results=50)) == 1


async def test_upsert_with_same_id_replaces(store: VectorStore, base: str) -> None:
    await store.upsert(base, ["a"], ["old text"], [{"v": 1}])
    await store.upsert(base, ["a"], ["new text"], [{"v": 2}])

    assert await store.count(base) == 1
    assert (await store.query(base, "new text", n_results=1))[0].text == "new text"


async def test_get_and_delete_by_filter(store: VectorStore, base: str) -> None:
    await store.upsert(base, ["a", "b"], ["x", "y"], [{"source": "f1"}, {"source": "f2"}])

    assert [i for i, _ in await store.get(base, where={"source": "f1"})] == ["a"]
    await store.delete(base, where={"source": "f1"})
    assert await store.count(base) == 1


async def test_delete_without_filter_is_refused(store: VectorStore, base: str) -> None:
    with pytest.raises(ValueError, match="Refusing"):
        await store.delete(base)


# ------------------------------------------------------------- memory index
async def test_memory_index_round_trip(store: VectorStore, base: str) -> None:
    index = MemoryVectorIndex(store, collection=base)

    await index.upsert(1, "User knows Python and SQL.")
    await index.upsert(2, "User likes cricket.")
    sims = await index.similarities("python skills")

    assert sims[1] > sims[2]
    await index.delete(1)
    assert 1 not in await index.similarities("python skills")


async def test_memory_index_sync_adds_missing_and_removes_stale(store: VectorStore, base: str) -> None:
    index = MemoryVectorIndex(store, collection=base)
    await index.upsert(1, "User likes chai.")
    await index.upsert(99, "deleted from the database long ago")

    added = await index.sync({1: "User likes chai.", 2: "User lives in Hyderabad."})

    assert added == 1  # only memory 2 was missing
    assert set(await index.similarities("anything", limit=10)) == {1, 2}  # 99 removed
