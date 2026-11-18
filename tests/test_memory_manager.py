"""Tests for MemoryManager.

UNIT tests: the LLM and both database-backed stores are create_autospec mocks, so we
test ONLY the manager's orchestration logic (order of calls, validation, redaction).
One INTEGRATION test at the end uses the real stores with in-memory SQLite.
"""

from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.config import Settings
from app.database.connection import Database
from app.llm.client import LLMError
from app.memory.long_term import LongTermMemory, MemoryRejected
from app.memory.manager import MemoryManager
from app.memory.schemas import MemoryExtraction, MemoryOperation, MemoryRecord, ScoredMemory
from app.memory.short_term import ConversationContext, ConversationStore, StoredMessage

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 7, tzinfo=UTC)


def record(memory_id: int, content: str, importance: int = 3) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id, content=content, category="profile", importance=importance,
        source="test", created_at=NOW, updated_at=NOW,
    )


def scored(rec: MemoryRecord, relevance: float = 1.0) -> ScoredMemory:
    return ScoredMemory(memory=rec, score=0.5, relevance=relevance, recency=1.0)


@pytest.fixture
def long_term() -> LongTermMemory:
    mock = create_autospec(LongTermMemory, instance=True)
    mock.search.return_value = []  # by default: nothing remembered
    return mock


@pytest.fixture
def conversations() -> ConversationStore:
    mock = create_autospec(ConversationStore, instance=True)
    mock.get_context.return_value = ConversationContext(summary="", recent=[])
    mock.count_unsummarized.return_value = 0
    return mock


@pytest.fixture
def manager(mock_llm, conversations, long_term) -> MemoryManager:
    mock_llm.generate.return_value = "Hello!"
    mock_llm.structured.return_value = MemoryExtraction()  # extract nothing by default
    settings = Settings(_env_file=None, google_api_key="k")
    return MemoryManager(mock_llm, conversations, long_term, settings)


# ---------------------------------------------------------------- chat turn
async def test_chat_turn_replies_and_stores_both_messages(manager, mock_llm, conversations) -> None:
    turn = await manager.chat("hi there", session_id="s1")

    assert turn.reply == "Hello!" and turn.session_id == "s1"
    mock_llm.generate.assert_awaited_once()
    # assert_any_await: these exact calls happened (in any order among others).
    conversations.add_message.assert_any_await("s1", "user", "hi there")
    conversations.add_message.assert_any_await("s1", "assistant", "Hello!")


async def test_new_session_id_is_generated(manager) -> None:
    turn = await manager.chat("hi")

    assert len(turn.session_id) == 32  # uuid4().hex


async def test_secrets_are_redacted_before_llm_and_storage(manager, mock_llm, conversations) -> None:
    await manager.chat("my key is sk-abcdefghijklmnopqrstuvwxyz123456", session_id="s")

    prompt = mock_llm.generate.await_args.args[0]
    assert "sk-abc" not in prompt[-1].content and "[REDACTED]" in prompt[-1].content
    stored = conversations.add_message.await_args_list[0].args[2]
    assert "sk-abc" not in stored
    # Long-term search and extraction also only ever saw the redacted text.
    for call in mock_llm.structured.await_args_list:
        assert all("sk-abc" not in m.content for m in call.args[0])


async def test_recalled_memories_and_history_reach_the_prompt(
    manager, mock_llm, long_term, conversations
) -> None:
    long_term.search.return_value = [scored(record(1, "User lives in Hyderabad.", importance=4))]
    conversations.get_context.return_value = ConversationContext(
        summary="Talked about jobs.",
        recent=[StoredMessage(id=1, role="user", content="earlier q", created_at=NOW),
                StoredMessage(id=2, role="assistant", content="earlier a", created_at=NOW)],
    )

    turn = await manager.chat("Which city?", session_id="s")

    system, *history, latest = mock_llm.generate.await_args.args[0]
    assert "User lives in Hyderabad." in system.content
    assert "Talked about jobs." in system.content
    assert history == [HumanMessage("earlier q"), AIMessage("earlier a")]
    assert latest == HumanMessage("Which city?")
    assert [m.content for m in turn.memories_used] == ["User lives in Hyderabad."]


async def test_core_memories_fill_empty_slots(manager, long_term) -> None:
    core = record(7, "User is named Ravi.", importance=5)
    minor = record(8, "User likes chai.", importance=2)
    # 1st search (by keywords) finds nothing; 2nd (empty query) ranks by importance.
    long_term.search.side_effect = [[], [scored(core, 0.0), scored(minor, 0.0)]]
    manager._settings = Settings(_env_file=None, google_api_key="k", memory_extraction_enabled=False)

    turn = await manager.chat("Which city should I job-hunt in?", session_id="s")

    assert [m.content for m in turn.memories_used] == ["User is named Ravi."]  # minor excluded


async def test_extraction_failure_does_not_break_chat(manager, mock_llm) -> None:
    mock_llm.structured.side_effect = LLMError("extraction model is down")

    turn = await manager.chat("hello", session_id="s")

    assert turn.reply == "Hello!" and turn.memory_changes == []


async def test_extraction_disabled_makes_no_extra_llm_call(manager, mock_llm) -> None:
    manager._settings = Settings(_env_file=None, google_api_key="k", memory_extraction_enabled=False)

    await manager.chat("hello", session_id="s")

    mock_llm.structured.assert_not_awaited()


async def test_invalid_session_id_rejected(manager, mock_llm) -> None:
    with pytest.raises(ValueError, match="session_id"):
        await manager.chat("hi", session_id="../etc/passwd")
    mock_llm.generate.assert_not_awaited()


# ------------------------------------------------------- applying operations
def ops(*operations: MemoryOperation) -> MemoryExtraction:
    return MemoryExtraction(operations=list(operations))


async def test_add_operation_calls_long_term_add(manager, long_term) -> None:
    long_term.add.return_value = (record(1, "User is named Ravi."), True)

    changes = await manager.apply_operations(
        ops(MemoryOperation(action="add", content="User is named Ravi.", category="profile", importance=5)),
        allowed_ids=set(), source="chat:s",
    )

    long_term.add.assert_awaited_once_with(
        "User is named Ravi.", category="profile", importance=5, source="chat:s"
    )
    assert changes[0].applied and changes[0].memory_id == 1


async def test_update_and_delete_only_for_shown_ids(manager, long_term) -> None:
    long_term.update.return_value = record(1, "User lives in Hyderabad.")

    changes = await manager.apply_operations(
        ops(
            MemoryOperation(action="update", memory_id=1, content="User lives in Hyderabad."),
            MemoryOperation(action="delete", memory_id=99),  # never shown to the LLM
        ),
        allowed_ids={1}, source="t",
    )

    assert [c.applied for c in changes] == [True, False]
    assert "not among the memories shown" in changes[1].reason
    long_term.delete.assert_not_awaited()  # the database was never touched for id 99


async def test_rejected_content_is_reported(manager, long_term) -> None:
    long_term.add.side_effect = MemoryRejected("Memory looks like it contains a secret")

    changes = await manager.apply_operations(
        ops(MemoryOperation(action="add", content="User's password: hunter2")),
        allowed_ids=set(), source="t",
    )

    assert changes[0].applied is False and "secret" in changes[0].reason


async def test_operation_count_is_limited(manager, long_term) -> None:
    long_term.add.return_value = (record(1, "x"), True)
    many = [MemoryOperation(action="add", content=f"User fact {i}.") for i in range(9)]

    changes = await manager.apply_operations(ops(*many), allowed_ids=set(), source="t")

    assert len(changes) == 5 and long_term.add.await_count == 5


async def test_extractor_sees_memories_even_without_shared_words(manager, mock_llm, long_term) -> None:
    long_term.search.return_value = [scored(record(4, "User lives in Pune."), relevance=0.0)]

    await manager.extract_memories("I moved to Hyderabad", source="t")

    # min_relevance=0.0 is what lets "Pune" reach the extractor for a "Hyderabad" message.
    assert long_term.search.await_args.kwargs["min_relevance"] == 0.0
    human_prompt = mock_llm.structured.await_args.args[0][-1].content
    assert "[id 4] User lives in Pune." in human_prompt


# ------------------------------------------------------------ summarization
async def test_long_history_is_summarized(manager, mock_llm, conversations) -> None:
    old = [StoredMessage(id=i, role="user", content=f"q{i}", created_at=NOW) for i in (1, 2, 3)]
    conversations.count_unsummarized.return_value = 25  # above memory_summarize_after (20)
    conversations.oldest_unsummarized.return_value = old
    mock_llm.generate.side_effect = ["reply", "User asked three questions."]

    turn = await manager.chat("q4", session_id="s")

    assert turn.summarized is True
    conversations.save_summary.assert_awaited_once_with("s", "User asked three questions.", [1, 2, 3])


async def test_no_summary_when_history_is_short(manager, conversations) -> None:
    turn = await manager.chat("hi", session_id="s")

    assert turn.summarized is False
    conversations.save_summary.assert_not_awaited()


# ------------------------------------------------------- integration (real DB)
async def test_integration_memory_round_trip_with_real_database(mock_llm) -> None:
    """Only the LLM is mocked: stores, SQL and retrieval are real (in-memory SQLite)."""
    database = Database("sqlite://")
    database.create_tables()
    manager = MemoryManager(
        mock_llm, ConversationStore(database), LongTermMemory(database),
        Settings(_env_file=None, google_api_key="k"),
    )
    mock_llm.generate.side_effect = ["Nice to meet you!", "Hyderabad has many AI jobs."]
    mock_llm.structured.side_effect = [
        ops(MemoryOperation(action="add", content="User lives in Hyderabad.", category="profile", importance=4)),
        MemoryExtraction(),
    ]

    await manager.chat("I live in Hyderabad", session_id="first")
    turn = await manager.chat("Which city should I search in?", session_id="second")

    assert [m.content for m in turn.memories_used] == ["User lives in Hyderabad."]
    assert len(await manager.conversations.history("first")) == 2
