"""Tests for WorkingMemory (in RAM) and ConversationStore (database)."""

import pytest

from app.database.connection import Database
from app.memory.short_term import ConversationStore, WorkingMemory


# ------------------------------------------------------------ working memory
def test_working_memory_records_task_results() -> None:
    memory = WorkingMemory("goal")
    memory.add("task_result", "10 jobs found", task_id="t1")
    memory.add("observation", "site was slow")
    memory.add("task_result", "updated: 12 jobs found", task_id="t1")

    assert memory.task_result("t1") == "updated: 12 jobs found"  # latest wins
    assert memory.task_result("t9") is None
    assert len(memory.entries({"t1"})) == 2


def test_working_memory_is_bounded() -> None:
    memory = WorkingMemory("goal", max_entries=3)
    for i in range(10):
        memory.add("note", f"note {i}")

    assert [e.content for e in memory.entries()] == ["note 7", "note 8", "note 9"]


def test_long_entries_are_cut() -> None:
    memory = WorkingMemory("goal", max_entry_chars=10)
    memory.add("note", "x" * 100)

    assert memory.entries()[0].content == "x" * 10 + " ...[cut]"


def test_render_keeps_newest_when_over_budget() -> None:
    memory = WorkingMemory("goal")
    for i in range(5):
        memory.add("note", f"entry-{i} " + "y" * 30)

    rendered = memory.render(max_chars=100)

    assert "entry-4" in rendered and "entry-0" not in rendered
    assert WorkingMemory("g").render() == "(nothing yet)"


# --------------------------------------------------------- conversation store
@pytest.fixture
def store() -> ConversationStore:
    database = Database("sqlite://")
    database.create_tables()
    return ConversationStore(database)


@pytest.mark.anyio
async def test_messages_are_stored_in_order(store: ConversationStore) -> None:
    for i in range(3):
        await store.add_message("s1", "user", f"q{i}")
        await store.add_message("s1", "assistant", f"a{i}")

    context = await store.get_context("s1", recent_limit=4)

    assert [m.content for m in context.recent] == ["q1", "a1", "q2", "a2"]
    assert context.summary == ""


@pytest.mark.anyio
async def test_sessions_are_separate(store: ConversationStore) -> None:
    await store.add_message("a", "user", "hello from a")
    await store.add_message("b", "user", "hello from b")

    assert [m.content for m in await store.history("a")] == ["hello from a"]


@pytest.mark.anyio
async def test_summary_marks_messages(store: ConversationStore) -> None:
    for i in range(6):
        await store.add_message("s", "user", f"m{i}")

    old = await store.oldest_unsummarized("s", keep_recent=2)
    assert [m.content for m in old] == ["m0", "m1", "m2", "m3"]

    await store.save_summary("s", "User said m0..m3", [m.id for m in old])

    context = await store.get_context("s", recent_limit=10)
    assert context.summary == "User said m0..m3"
    assert [m.content for m in context.recent] == ["m4", "m5"]  # summarized ones excluded
    assert await store.count_unsummarized("s") == 2
    assert len(await store.history("s")) == 6  # full history is kept for the user


@pytest.mark.anyio
async def test_delete_session(store: ConversationStore) -> None:
    await store.add_message("s", "user", "bye")

    assert await store.delete_session("s") is True
    assert await store.history("s") == []
    assert await store.delete_session("s") is False
