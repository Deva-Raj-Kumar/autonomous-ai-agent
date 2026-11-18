"""MemoryManager: one chat turn with all three kinds of memory.

    user message
      1. redact secrets           (before ANYTHING sees or stores the text)
      2. recall                   long-term memories relevant to the message
                                  + conversation summary + recent messages
      3. in parallel:
           a. reply               LLM answers using that context
           b. extract             LLM proposes memory operations; CODE validates them
      4. store                    both messages in the conversation history
      5. compress                 if the history is long, fold the oldest messages into
                                  the running summary

Steps 3a and 3b don't depend on each other, so asyncio.gather runs them at the same
time, which saves a whole LLM round-trip of waiting.
"""

import asyncio
import logging
import re
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import Settings, get_settings
from app.llm.client import LLMError
from app.llm.prompts import (
    AGENT_SYSTEM_PROMPT,
    MEMORY_CONTEXT_TEMPLATE,
    MEMORY_EXTRACTION_PROMPT,
    SUMMARIZE_CONVERSATION_PROMPT,
)
from app.llm.service import LLMService
from app.memory.long_term import LongTermMemory, MemoryRejected
from app.memory.schemas import ChatTurn, MemoryChange, MemoryExtraction, MemoryOperation, MemoryRecord
from app.memory.short_term import ConversationStore
from app.safety.secrets import redact_secrets

logger = logging.getLogger(__name__)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_OPERATIONS_PER_MESSAGE = 5
EXTRACTION_CONTEXT_MEMORIES = 20  # existing memories shown to the extractor (conflict check)


class MemoryManager:
    def __init__(
        self,
        llm: LLMService,
        conversations: ConversationStore,
        long_term: LongTermMemory,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self.conversations = conversations
        self.long_term = long_term
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ chat
    async def chat(self, message: str, session_id: str | None = None) -> ChatTurn:
        session_id = session_id or uuid4().hex
        if not SESSION_ID_PATTERN.match(session_id):
            raise ValueError("session_id may only contain letters, digits, '-' and '_' (max 64).")

        # 1. Redact secrets before the LLM provider or the database ever sees them.
        message = redact_secrets(message)

        # 2. Recall.
        memories = await self.recall(message)
        context = await self.conversations.get_context(
            session_id, self._settings.memory_recent_messages
        )
        prompt = self._build_chat_messages(message, memories, context.summary, context.recent)

        # 3. Reply and extract at the same time.
        extraction = (
            self.extract_memories(message, source=f"chat:{session_id}")
            if self._settings.memory_extraction_enabled
            else _no_changes()
        )
        reply, changes = await asyncio.gather(self._llm.generate(prompt, label="chat"), extraction)

        # 4. Store the turn.
        await self.conversations.add_message(session_id, "user", message)
        await self.conversations.add_message(session_id, "assistant", reply)

        # 5. Compress old history if needed.
        summarized = await self._maybe_summarize(session_id)

        return ChatTurn(
            session_id=session_id,
            reply=reply,
            memories_used=memories,
            memory_changes=changes,
            summarized=summarized,
        )

    async def recall(self, message: str) -> list[MemoryRecord]:
        """Memories for the prompt = keyword-relevant ones + CORE ones to fill the rest.

        Keyword search alone misses related words ("city" never matches "Hyderabad").
        Core memories (importance >= 4: name, studies, main goal) are useful in almost
        every conversation, so they fill any free slots. This is the "user profile"
        pattern. Phase 6 improves the relevant part with semantic (embedding) search.
        """
        limit = self._settings.memory_max_results
        relevant = await self.long_term.search(message, limit=limit)
        chosen = [s.memory for s in relevant]
        if len(chosen) < limit:
            # An empty query ranks purely by importance + recency.
            for s in await self.long_term.search("", limit=limit * 2):
                if len(chosen) >= limit:
                    break
                if s.memory.importance >= 4 and s.memory.id not in {m.id for m in chosen}:
                    chosen.append(s.memory)
        return chosen

    def _build_chat_messages(
        self, message: str, memories: list[MemoryRecord], summary: str, recent: list
    ) -> list[BaseMessage]:
        memory_lines = "\n".join(f"- {m.content}" for m in memories) or "(none)"
        system = AGENT_SYSTEM_PROMPT + MEMORY_CONTEXT_TEMPLATE.format(
            memories=memory_lines, summary=summary or "(none)"
        )
        history: list[BaseMessage] = [
            HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in recent
        ]
        return [SystemMessage(system), *history, HumanMessage(message)]

    # ------------------------------------------------------------ extraction
    async def extract_memories(self, message: str, *, source: str) -> list[MemoryChange]:
        """Ask the LLM what to remember, then validate and apply each operation.

        Never raises: a memory failure must not break the chat reply.
        """
        # min_relevance=0: show memories even with NO shared words. "I moved to Hyderabad"
        # shares no word with "User lives in Pune", but the LLM must see it to update it.
        # Relevant memories still rank first (relevance has the biggest weight).
        related = await self.long_term.search(
            message, limit=EXTRACTION_CONTEXT_MEMORIES, min_relevance=0.0, mark_accessed=False
        )
        shown = {s.memory.id: s.memory for s in related}
        existing = "\n".join(f"[id {m.id}] {m.content}" for m in shown.values()) or "(none)"
        prompt = MEMORY_EXTRACTION_PROMPT.invoke({"existing": existing, "message": message})
        try:
            extraction = await self._llm.structured(prompt.to_messages(), MemoryExtraction)
        except LLMError as exc:
            logger.warning("Memory extraction failed, skipping: %s", exc)
            return []
        return await self.apply_operations(extraction, allowed_ids=set(shown), source=source)

    async def apply_operations(
        self, extraction: MemoryExtraction, *, allowed_ids: set[int], source: str
    ) -> list[MemoryChange]:
        """Validate every proposed operation in CODE before touching the database.

        - update/delete may only target memories that were SHOWN to the LLM
          (it can't edit or delete memories it never saw)
        - content goes through validate_content (no secrets, length limits)
        - at most MAX_OPERATIONS_PER_MESSAGE per message
        """
        changes: list[MemoryChange] = []
        for op in extraction.operations[:MAX_OPERATIONS_PER_MESSAGE]:

            # op=op binds THIS iteration's operation (a closure would otherwise see
            # whatever `op` is when it is called: the classic late-binding bug, B023).
            def change(applied: bool, reason: str = "", memory_id: int | None = op.memory_id,
                       op: MemoryOperation = op) -> MemoryChange:
                return MemoryChange(
                    action=op.action, memory_id=memory_id, content=op.content,
                    applied=applied, reason=reason,
                )

            if op.action in ("update", "delete") and op.memory_id not in allowed_ids:
                changes.append(change(False, "memory_id was not among the memories shown"))
                continue
            try:
                if op.action == "add":
                    record, created = await self.long_term.add(
                        op.content, category=op.category, importance=op.importance, source=source
                    )
                    changes.append(change(True, "" if created else "duplicate: refreshed", record.id))
                elif op.action == "update":
                    record = await self.long_term.update(
                        op.memory_id, op.content, category=op.category, importance=op.importance
                    )
                    changes.append(change(record is not None, "" if record else "not found"))
                else:
                    deleted = await self.long_term.delete(op.memory_id)
                    changes.append(change(deleted, "" if deleted else "not found"))
            except MemoryRejected as exc:
                changes.append(change(False, str(exc)))

        for c in changes:
            logger.info("MEMORY %s id=%s applied=%s %s %s", c.action, c.memory_id, c.applied, c.reason, c.content[:80])
        return changes

    # --------------------------------------------------------- summarization
    async def _maybe_summarize(self, session_id: str) -> bool:
        """Fold the oldest messages into the running summary once history gets long."""
        if await self.conversations.count_unsummarized(session_id) <= self._settings.memory_summarize_after:
            return False
        old = await self.conversations.oldest_unsummarized(
            session_id, keep_recent=self._settings.memory_recent_messages
        )
        if not old:
            return False
        context = await self.conversations.get_context(session_id, recent_limit=0)
        transcript = "\n".join(f"{m.role}: {m.content}" for m in old)
        prompt = SUMMARIZE_CONVERSATION_PROMPT.format(
            summary=context.summary or "(empty)", messages=transcript
        )
        try:
            summary = await self._llm.generate([HumanMessage(prompt)], label="summarize")
        except LLMError as exc:
            logger.warning("Summarization failed, will retry next turn: %s", exc)
            return False
        await self.conversations.save_summary(session_id, summary.strip(), [m.id for m in old])
        logger.info("Summarized %d old messages in session %s", len(old), session_id)
        return True

    # ----------------------------------------------------- context for agents
    async def recall_for(self, text: str) -> str:
        """Relevant long-term memories as prompt text. Phase 7's executor and the
        planner can use this to personalize their work."""
        return "\n".join(f"- {m.content}" for m in await self.recall(text)) or "(none)"


async def _no_changes() -> list[MemoryChange]:
    return []
