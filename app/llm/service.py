"""LLMService: the one class the rest of the app uses to talk to the LLM.

It wraps a LangChain chat model and offers three abilities:
  1. chat()           -> plain text answer
  2. structured()     -> answer as a validated Pydantic object (structured outputs)
  3. run_with_tools() -> lets the model call Python functions (function calling)

All methods are async (`async def` + `await`), so the FastAPI server can serve other
requests while it waits for the LLM's network response.
"""

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.client import LLMError, create_chat_model, is_temporary_error
from app.llm.prompts import AGENT_SYSTEM_PROMPT, GOAL_ANALYSIS_PROMPT
from app.llm.schemas import GoalAnalysis, ToolCallRecord, ToolRunResult

logger = logging.getLogger(__name__)

# A type variable: structured(..., schema=GoalAnalysis) returns a GoalAnalysis,
# structured(..., schema=OtherModel) returns an OtherModel. Editors understand this.
SchemaT = TypeVar("SchemaT", bound=BaseModel)
T = TypeVar("T")

MAX_TOOL_OUTPUT_CHARS = 4_000  # stop one huge tool result from flooding the context window


class LLMService:
    """High-level, provider-independent access to the LLM."""

    # After a model reports "overloaded", try the others first for this many seconds.
    COOLDOWN_SECONDS = 60.0

    def __init__(self, model: BaseChatModel, fallbacks: Sequence[BaseChatModel] = (), *, clock=time.monotonic) -> None:
        # The models are passed in ("dependency injection"), so tests can pass fake ones.
        self._model = model
        self._models = [model, *fallbacks]
        self._cooling_until: dict[int, float] = {}  # model index -> time it may lead again
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "LLMService":
        """Create a service using the provider and model from .env, plus its fallbacks."""
        settings = settings or get_settings()
        fallbacks = [create_chat_model(settings, model_name=name) for name in settings.fallback_models]
        return cls(create_chat_model(settings), fallbacks)

    async def _call_with_fallback(self, call: Callable[[BaseChatModel], Awaitable[T]], what: str) -> T:
        """Run `call` on the first model that works.

        Order: healthy models first (in configured order), then ones cooling down. Only
        TEMPORARY provider errors move on to the next model; a real error (bad request,
        bad key) is raised at once, because another model would fail the same way.
        """
        now = self._clock()
        order = sorted(range(len(self._models)), key=lambda i: (self._cooling_until.get(i, 0) > now, i))
        last_error: Exception | None = None
        for position, index in enumerate(order):
            try:
                result = await call(self._models[index])
            except Exception as exc:
                if not is_temporary_error(exc):
                    raise LLMError(f"{what} failed: {exc}") from exc
                last_error = exc
                self._cooling_until[index] = self._clock() + self.COOLDOWN_SECONDS
                if position + 1 < len(order):
                    logger.warning("%s: model #%d temporarily unavailable (%s); trying a fallback model",
                                   what, index, type(exc).__name__)
                continue
            self._cooling_until.pop(index, None)
            return result
        raise LLMError(f"{what} failed: every model is temporarily unavailable ({last_error})") from last_error

    # ------------------------------------------------------------------ chat
    async def chat(self, user_message: str, *, system_prompt: str = AGENT_SYSTEM_PROMPT) -> str:
        """Send one message and return the model's text reply."""
        return await self.generate([SystemMessage(system_prompt), HumanMessage(user_message)])

    async def generate(self, messages: Sequence[BaseMessage], *, label: str = "chat") -> str:
        """Send a full message list (system + history + new message); return the text reply."""
        reply = await self._call_with_fallback(lambda model: model.ainvoke(list(messages)), "Chat request")
        self._log_usage(label, reply)
        return reply.text  # .text joins all text parts and skips "thinking" parts

    # ------------------------------------------------------------ structured
    async def structured(
        self, messages: Sequence[BaseMessage] | str, schema: type[SchemaT]
    ) -> SchemaT:
        """Ask the model for an answer that matches `schema`, and return it as that type.

        method="json_schema" uses the provider's native structured-output mode: the
        provider itself guarantees the JSON matches the schema. It is more reliable
        than asking for JSON in the prompt.
        """
        result = await self._call_with_fallback(
            lambda model: model.with_structured_output(schema, method="json_schema").ainvoke(messages),
            "Structured output request",
        )
        if not isinstance(result, schema):  # defensive check: never trust, always verify
            raise LLMError(f"Model returned {type(result).__name__}, expected {schema.__name__}")
        return result

    async def analyze_goal(self, goal: str) -> GoalAnalysis:
        """Turn a natural-language goal into a structured GoalAnalysis."""
        messages = GOAL_ANALYSIS_PROMPT.invoke({"goal": goal}).to_messages()
        return await self.structured(messages, GoalAnalysis)

    # -------------------------------------------------------- function calling
    async def run_with_tools(
        self,
        user_message: str,
        tools: Sequence[BaseTool],
        *,
        max_rounds: int = 8,
        system_prompt: str = AGENT_SYSTEM_PROMPT,
    ) -> ToolRunResult:
        """Let the model call tools in a loop until it gives a final answer.

        The loop (this is the heart of every agent):
          1. Send the conversation + tool descriptions to the model.
          2. If the reply contains tool_calls -> run each tool, append the results as
             ToolMessages, and go back to step 1.
          3. If the reply has no tool_calls -> it is the final answer. Stop.
        `max_rounds` is a safety limit so a confused model can't loop forever. 8 leaves
        room for a 3-tool task plus a recovery step (e.g. retrying a wrong file name).
        """
        tools_by_name = {t.name: t for t in tools}
        # bind_tools sends each tool's name, description and JSON schema with every request.
        tool_list = list(tools)
        bound: dict[int, BaseChatModel] = {}  # bind once per model, not once per round

        def with_tools(model: BaseChatModel):
            if id(model) not in bound:
                bound[id(model)] = model.bind_tools(tool_list)
            return bound[id(model)]

        messages: list[BaseMessage] = [SystemMessage(system_prompt), HumanMessage(user_message)]
        records: list[ToolCallRecord] = []

        for round_number in range(1, max_rounds + 1):
            ai_message: AIMessage = await self._call_with_fallback(
                lambda model: with_tools(model).ainvoke(messages), "Tool-calling request"
            )
            self._log_usage(f"tools round {round_number}", ai_message)

            # Keep the model's own message in the history. The next request must show
            # the model which calls it asked for (Gemini also stores hidden reasoning
            # "signatures" in it, which must be sent back unchanged).
            messages.append(ai_message)

            if not ai_message.tool_calls:
                return ToolRunResult(
                    answer=ai_message.text, tool_calls=records, rounds=round_number
                )

            for call in ai_message.tool_calls:
                output, success = await self._execute_tool_call(call, tools_by_name)
                records.append(
                    ToolCallRecord(
                        tool_name=call["name"],
                        arguments=call["args"],
                        output=output,
                        success=success,
                    )
                )
                # tool_call_id links this result to the exact request it answers.
                messages.append(
                    ToolMessage(content=output, tool_call_id=call["id"], name=call["name"])
                )

        raise LLMError(f"No final answer after {max_rounds} rounds of tool calls.")

    @staticmethod
    async def _execute_tool_call(
        call: dict, tools_by_name: dict[str, BaseTool]
    ) -> tuple[str, bool]:
        """Run one requested tool. Errors are returned as text, never raised.

        Returning the error lets the model see what went wrong and correct itself
        (e.g. fix a bad argument) instead of crashing the whole run.
        """
        tool = tools_by_name.get(call["name"])
        if tool is None:  # the model asked for a tool we never offered: refuse
            logger.warning("Model requested unknown tool %r", call["name"])
            return f"Error: tool '{call['name']}' does not exist.", False
        try:
            # ainvoke validates the arguments against the tool's schema first.
            result = await tool.ainvoke(call["args"])
        except Exception as exc:
            logger.warning("Tool %s failed: %s", call["name"], exc)
            return f"Error while running {call['name']}: {exc}", False
        # DEBUG, not INFO: the ToolRegistry already writes an audit line for every call.
        logger.debug("Tool %s(%s) -> %s", call["name"], call["args"], str(result)[:200])
        return str(result)[:MAX_TOOL_OUTPUT_CHARS], True

    @staticmethod
    def _log_usage(label: str, message: AIMessage) -> None:
        """Log token usage. Tokens = cost, so always measure them."""
        usage = getattr(message, "usage_metadata", None)
        if usage:
            logger.info(
                "LLM %s: %s input + %s output tokens",
                label,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
            )
