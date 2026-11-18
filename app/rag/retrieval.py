"""Retrieval: find the chunks that answer a question, then answer with citations.

Two-stage retrieval, the standard RAG pattern:

  1. RECALL  (fast, broad):  vector search returns ~20 candidate chunks close in meaning.
  2. RERANK  (careful):      re-score the candidates and keep the best few (~4).
       hybrid: 0.7 * semantic relevance + 0.3 * keyword overlap. Embeddings blur exact
               terms (names, numbers like "LPA", tech words like "FastAPI"); keyword
               overlap brings them back. Free.
       llm:    the LLM scores every candidate 0-10 in ONE structured call. Smarter,
               costs one LLM call.
     Then near-duplicate chunks (from overlap) are dropped, so the LLM gets 4 DIFFERENT pieces.

Then GENERATION: number the chunks [1]..[n], tell the LLM to answer only from them and
cite numbers, and finally check in code that every cited number really exists.
"""

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm.client import LLMError
from app.llm.prompts import RAG_ANSWER_PROMPT, RERANK_SYSTEM_PROMPT, wrap_untrusted
from app.llm.service import LLMService
from app.memory.long_term import jaccard, tokenize
from app.memory.vector_store import VectorHit, VectorStore
from app.rag.ingestion import NO_PAGE, DocumentIngestor

logger = logging.getLogger(__name__)

HYBRID_WEIGHTS = (0.7, 0.3)  # (semantic, keyword)
DUPLICATE_OVERLAP = 0.7  # chunks sharing >= 70% of their words count as duplicates
NO_RESULTS_ANSWER = "I couldn't find anything about that in the knowledge base."


class RetrievedChunk(BaseModel):
    id: str
    text: str
    source: str
    page: int | None
    similarity: float = Field(description="Raw cosine similarity from the vector search.")
    score: float = Field(description="Final score after reranking (0-1).")

    @property
    def citation_label(self) -> str:
        return f"{self.source}, page {self.page}" if self.page else self.source


class RAGAnswer(BaseModel):
    answer: str
    sources: list[RetrievedChunk]
    cited: list[int] = Field(description="Source numbers the answer actually cites.")
    invalid_citations: list[int] = Field(description="Cited numbers that don't exist (a red flag).")


class _PassageScore(BaseModel):
    index: int = Field(description="Passage number as shown.")
    score: int = Field(description="0 = useless, 10 = directly answers the question.")


class _RerankResult(BaseModel):
    scores: list[_PassageScore]


def keyword_overlap(query: str, text: str) -> float:
    """Fraction of the query's words found in the text (0..1)."""
    query_words = tokenize(query)
    return len(query_words & tokenize(text)) / len(query_words) if query_words else 0.0


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Numbered sources for the prompt. Document text is untrusted, so it is wrapped."""
    blocks = [f"[{n}] ({c.citation_label})\n{c.text}" for n, c in enumerate(chunks, start=1)]
    return wrap_untrusted("\n\n".join(blocks), source="knowledge_base")


def extract_citations(answer: str) -> list[int]:
    """[1] and [2][3] -> [1, 2, 3] (unique, in order of first appearance)."""
    seen: list[int] = []
    for number in (int(n) for n in re.findall(r"\[(\d+)\]", answer)):
        if number not in seen:
            seen.append(number)
    return seen


class KnowledgeBase:
    """Facade for everything RAG: ingestion, search, and answering questions."""

    def __init__(
        self,
        store: VectorStore,
        ingestor: DocumentIngestor,
        *,
        top_k: int = 4,
        candidates: int = 20,
        reranker: str = "hybrid",
    ) -> None:
        self._store = store
        self.ingestor = ingestor
        self._top_k = top_k
        self._candidates = candidates
        self._reranker = reranker

    async def search(
        self, query: str, *, k: int | None = None, llm: LLMService | None = None
    ) -> list[RetrievedChunk]:
        """Best chunks for `query`, best first. Empty list = nothing relevant."""
        k = k or self._top_k
        embedder = self._store.embedder
        # 1. Recall.
        hits = await self._store.query(self.ingestor.collection, query, n_results=max(self._candidates, k))
        # Drop chunks below this model's "unrelated" threshold. This is what lets RAG
        # say "I don't know" instead of answering from irrelevant text.
        hits = [h for h in hits if h.similarity >= embedder.similarity_floor]
        if not hits:
            return []

        # 2. Rerank.
        if self._reranker == "llm" and llm is not None:
            scored = await self._llm_rerank(query, hits, llm)
        elif self._reranker == "none":
            scored = [(embedder.relevance(h.similarity), h) for h in hits]
        else:
            semantic_w, keyword_w = HYBRID_WEIGHTS
            scored = [
                (semantic_w * embedder.relevance(h.similarity) + keyword_w * keyword_overlap(query, h.text), h)
                for h in hits
            ]
        scored.sort(key=lambda pair: pair[0], reverse=True)

        # 3. Drop near-duplicates, keep the top k.
        chosen: list[RetrievedChunk] = []
        chosen_words: list[set[str]] = []
        for score, hit in scored:
            words = tokenize(hit.text)
            if any(jaccard(words, other) >= DUPLICATE_OVERLAP for other in chosen_words):
                continue
            chosen.append(_to_chunk(hit, score))
            chosen_words.append(words)
            if len(chosen) == k:
                break
        return chosen

    async def _llm_rerank(
        self, query: str, hits: list[VectorHit], llm: LLMService
    ) -> list[tuple[float, VectorHit]]:
        passages = "\n\n".join(f"Passage {i}:\n{h.text[:1_000]}" for i, h in enumerate(hits))
        messages = [
            SystemMessage(RERANK_SYSTEM_PROMPT),
            HumanMessage(f"Question: {query}\n\n{wrap_untrusted(passages, source='candidates')}"),
        ]
        try:
            result = await llm.structured(messages, _RerankResult)
        except LLMError as exc:  # the reranker is an optimization: fall back, don't fail
            logger.warning("LLM rerank failed, using vector order: %s", exc)
            return [(self._store.embedder.relevance(h.similarity), h) for h in hits]
        by_index = {s.index: max(0, min(10, s.score)) / 10 for s in result.scores}
        # Passages the LLM forgot to score keep a small vector-based score.
        return [
            (by_index.get(i, 0.1 * self._store.embedder.relevance(h.similarity)), h)
            for i, h in enumerate(hits)
        ]

    async def answer(self, question: str, llm: LLMService, *, k: int | None = None) -> RAGAnswer:
        """Retrieve, then generate an answer that cites its sources."""
        chunks = await self.search(question, k=k, llm=llm)
        if not chunks:
            # No relevant sources: answer honestly WITHOUT calling the LLM, which might
            # otherwise "helpfully" answer from its general knowledge.
            return RAGAnswer(answer=NO_RESULTS_ANSWER, sources=[], cited=[], invalid_citations=[])

        messages = RAG_ANSWER_PROMPT.invoke(
            {"context": build_context(chunks), "question": question}
        ).to_messages()
        text = await llm.generate(messages, label="rag")
        cited = extract_citations(text)
        invalid = [n for n in cited if not 1 <= n <= len(chunks)]
        if invalid:
            logger.warning("Answer cites non-existent sources %s", invalid)
        return RAGAnswer(
            answer=text,
            sources=chunks,
            cited=[n for n in cited if n not in invalid],
            invalid_citations=invalid,
        )


def _to_chunk(hit: VectorHit, score: float) -> RetrievedChunk:
    page = int(hit.metadata.get("page", NO_PAGE))
    return RetrievedChunk(
        id=hit.id,
        text=hit.text,
        source=str(hit.metadata.get("source", "?")),
        page=page if page != NO_PAGE else None,
        similarity=hit.similarity,
        score=round(score, 4),
    )


def build_knowledge_base(settings, store: VectorStore) -> KnowledgeBase:
    """Create the KnowledgeBase from settings (shared by the API and the CLI)."""
    ingestor = DocumentIngestor(
        store,
        settings.documents_dir,
        chunk_size=settings.rag_chunk_size,
        overlap=settings.rag_chunk_overlap,
        max_file_size_mb=settings.max_file_size_mb,
    )
    return KnowledgeBase(
        store,
        ingestor,
        top_k=settings.rag_top_k,
        candidates=settings.rag_candidates,
        reranker=settings.rag_reranker,
    )
