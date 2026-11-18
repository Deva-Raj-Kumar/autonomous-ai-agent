"""Unit tests for LLMService, with the chat model replaced by unittest.mock objects."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.llm.client import LLMError
from app.llm.example_tools import EXAMPLE_TOOLS, get_current_time
from app.llm.schemas import GoalAnalysis
from app.llm.service import LLMService
from tests.helpers import make_chat_model_mock, tool_call

pytestmark = pytest.mark.anyio  # every test in this file is async


def make_goal_analysis() -> GoalAnalysis:
    return GoalAnalysis(
        summary="Compare AI fresher job skills in two cities.",
        category="research",
        deliverables=["comparison report"],
        required_capabilities=["web_search", "report_generation", "database"],
        is_clear=True,
    )


def scripted_tool_model(*replies: AIMessage):
    """A chat model whose bind_tools(...).ainvoke returns `replies` one by one.

    MagicMock PITFALL: a mock remembers REFERENCES to its arguments, not copies.
    run_with_tools appends to the same message list after each call, so
    await_args_list would only show the final list. This side_effect saves a COPY
    of the messages at the moment of each call.
    """
    model = make_chat_model_mock()
    snapshots: list[list] = []
    queue = list(replies)

    async def respond(messages, *args, **kwargs):
        snapshots.append(list(messages))  # snapshot, not reference
        return queue.pop(0)

    model.bind_tools.return_value.ainvoke = AsyncMock(side_effect=respond)
    return model, snapshots


# -------------------------------------------------------------------- chat
async def test_chat_returns_text() -> None:
    model = make_chat_model_mock()
    model.ainvoke.return_value = AIMessage(content="Hello!")

    reply = await LLMService(model).chat("Hi")

    assert reply == "Hello!"
    model.ainvoke.assert_awaited_once()
    sent = model.ainvoke.await_args.args[0]  # the message list passed to ainvoke
    assert isinstance(sent[0], SystemMessage)
    assert sent[1] == HumanMessage("Hi")


async def test_chat_wraps_provider_errors() -> None:
    model = make_chat_model_mock()
    model.ainvoke.side_effect = TimeoutError("took too long")  # side_effect=exception -> raised

    with pytest.raises(LLMError, match="took too long"):
        await LLMService(model).chat("Hi")


# --------------------------------------------------------------- structured
async def test_analyze_goal_uses_native_structured_output() -> None:
    model = make_chat_model_mock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=make_goal_analysis())

    result = await LLMService(model).analyze_goal("Research AI jobs and write a report")

    assert isinstance(result, GoalAnalysis)
    model.with_structured_output.assert_called_once_with(GoalAnalysis, method="json_schema")


async def test_structured_rejects_wrong_type() -> None:
    model = make_chat_model_mock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"not": "a model"})

    with pytest.raises(LLMError, match="expected GoalAnalysis"):
        await LLMService(model).analyze_goal("anything")


async def test_structured_wraps_errors() -> None:
    model = make_chat_model_mock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=ValueError("bad json"))

    with pytest.raises(LLMError, match="bad json"):
        await LLMService(model).analyze_goal("anything")


# --------------------------------------------------------- function calling
async def test_tool_loop_runs_tool_and_returns_final_answer() -> None:
    model, snapshots = scripted_tool_model(
        AIMessage(content="", tool_calls=[tool_call("multiply_numbers", {"a": 23.5, "b": 19})]),
        AIMessage(content="23.5 x 19 = 446.5"),
    )

    result = await LLMService(model).run_with_tools("What is 23.5 * 19?", EXAMPLE_TOOLS)

    assert result.answer == "23.5 x 19 = 446.5"
    assert result.rounds == 2
    assert result.tool_calls[0].output == "446.5" and result.tool_calls[0].success
    model.bind_tools.assert_called_once_with(EXAMPLE_TOOLS)
    # The 2nd model call ended with the tool result, linked by tool_call_id.
    last_message = snapshots[1][-1]
    assert isinstance(last_message, ToolMessage) and last_message.tool_call_id == "call-1"


async def test_unknown_tool_is_refused_not_crashed() -> None:
    model, _ = scripted_tool_model(
        AIMessage(content="", tool_calls=[tool_call("delete_all_files", {})]),
        AIMessage(content="I can't do that."),
    )

    result = await LLMService(model).run_with_tools("clean my disk", EXAMPLE_TOOLS)

    assert result.tool_calls[0].success is False
    assert "does not exist" in result.tool_calls[0].output


async def test_invalid_tool_arguments_are_reported_to_model() -> None:
    model, snapshots = scripted_tool_model(
        AIMessage(content="", tool_calls=[tool_call("add_numbers", {"a": "lots", "b": 2})]),
        AIMessage(content="Sorry, I need numbers."),
    )

    result = await LLMService(model).run_with_tools("add lots and 2", EXAMPLE_TOOLS)

    assert result.tool_calls[0].success is False
    assert "Error" in snapshots[1][-1].content  # the model was told what went wrong


async def test_tool_loop_stops_at_max_rounds() -> None:
    endless = [
        AIMessage(content="", tool_calls=[tool_call("add_numbers", {"a": 1, "b": 1}, f"c{i}")])
        for i in range(5)
    ]
    model, snapshots = scripted_tool_model(*endless)

    with pytest.raises(LLMError, match="after 3 rounds"):
        await LLMService(model).run_with_tools("loop forever", EXAMPLE_TOOLS, max_rounds=3)
    assert len(snapshots) == 3  # exactly max_rounds model calls, then it stopped


async def test_example_time_tool_handles_bad_timezone() -> None:
    output = await get_current_time.ainvoke({"timezone": "Mars/Olympus"})

    assert output.startswith("Error: unknown timezone")


# ------------------------------------------------------- fallback models (Phase 15)
OVERLOADED = Exception(
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"
)


async def test_an_overloaded_model_falls_back_to_the_next_one() -> None:
    primary, backup = make_chat_model_mock(), make_chat_model_mock()
    primary.ainvoke.side_effect = OVERLOADED
    backup.ainvoke.return_value = AIMessage("from the backup model")

    reply = await LLMService(primary, [backup]).generate([HumanMessage("hi")])

    assert reply == "from the backup model"


async def test_a_real_error_is_raised_without_trying_other_models() -> None:
    primary, backup = make_chat_model_mock(), make_chat_model_mock()
    primary.ainvoke.side_effect = Exception("400 INVALID_ARGUMENT: bad request")

    with pytest.raises(LLMError, match="400"):
        await LLMService(primary, [backup]).generate([HumanMessage("hi")])
    backup.ainvoke.assert_not_awaited()  # a bad request is bad for every model


async def test_an_overloaded_model_cools_down_then_leads_again() -> None:
    now = [0.0]
    primary, backup = make_chat_model_mock(), make_chat_model_mock()
    primary.ainvoke.side_effect = [OVERLOADED, AIMessage("primary is back")]
    backup.ainvoke.return_value = AIMessage("backup")
    service = LLMService(primary, [backup], clock=lambda: now[0])

    assert await service.generate([HumanMessage("1")]) == "backup"
    assert await service.generate([HumanMessage("2")]) == "backup"  # primary skipped while cooling
    assert primary.ainvoke.await_count == 1

    now[0] += LLMService.COOLDOWN_SECONDS + 1
    assert await service.generate([HumanMessage("3")]) == "primary is back"


async def test_when_every_model_is_down_the_error_says_so() -> None:
    primary, backup = make_chat_model_mock(), make_chat_model_mock()
    primary.ainvoke.side_effect = OVERLOADED
    backup.ainvoke.side_effect = TimeoutError("read timed out")

    with pytest.raises(LLMError, match="every model is temporarily unavailable"):
        await LLMService(primary, [backup]).generate([HumanMessage("hi")])


@pytest.mark.parametrize(("error", "temporary"), [
    (OVERLOADED, True),
    (Exception("429 RESOURCE_EXHAUSTED: quota"), True),
    (TimeoutError(), True),
    (Exception("500 INTERNAL"), True),
    (Exception("400 INVALID_ARGUMENT"), False),
    (Exception("401 API key not valid"), False),
    (Exception("404 model not found"), False),
])
def test_temporary_errors_are_recognised(error: Exception, temporary: bool) -> None:
    from app.llm.client import is_temporary_error

    assert is_temporary_error(error) is temporary
