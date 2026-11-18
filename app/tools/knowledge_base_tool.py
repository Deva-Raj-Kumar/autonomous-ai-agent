"""search_knowledge_base: lets the agent look things up in YOUR ingested documents (RAG).

Returns the best chunks with numbered source labels, so the LLM can cite them.
Chunks come from uploaded files, so they are wrapped as untrusted data.
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.llm.prompts import wrap_untrusted
from app.tools.base import AgentTool

if TYPE_CHECKING:
    from app.rag.retrieval import KnowledgeBase


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=500, description="What to look up in the documents.")
    k: int = Field(default=4, ge=1, le=10, description="How many passages to return.")


class SearchKnowledgeBaseTool(AgentTool):
    name = "search_knowledge_base"
    input_model = KnowledgeSearchInput

    def __init__(self, knowledge_base: "KnowledgeBase") -> None:
        self._kb = knowledge_base

    async def run(self, args: KnowledgeSearchInput) -> str:  # type: ignore[override]
        chunks = await self._kb.search(args.query, k=args.k)
        if not chunks:
            return f'No relevant passages found in the knowledge base for "{args.query}".'
        blocks = [
            f"[{n}] ({c.citation_label}, relevance {c.score:.2f})\n{c.text}"
            for n, c in enumerate(chunks, start=1)
        ]
        return wrap_untrusted("\n\n".join(blocks), source="knowledge_base")
