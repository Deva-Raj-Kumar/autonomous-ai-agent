"""Retrieval tests: helpers, reranking modes, deduplication, answering with citations.

Reranking tests use a create_autospec(VectorStore) mock, so each test controls the exact
candidates and similarity scores. End-to-end tests use real ingestion + in-memory Chroma.
"""

import uuid
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from app.llm.client import LLMError
from app.memory.vector_store import VectorHit, VectorStore, make_chroma_client
from app.rag.embeddings import LocalEmbedder
from app.rag.ingestion import DocumentIngestor
from app.rag.retrieval import (
    NO_RESULTS_ANSWER,
    KnowledgeBase,
    RetrievedChunk,
    _PassageScore,
    _RerankResult,
    build_context,
    extract_citations,
    keyword_overlap,
)
from app.tools.knowledge_base_tool import KnowledgeSearchInput, SearchKnowledgeBaseTool
from tests.helpers import make_embedder_mock

pytestmark = pytest.mark.anyio


# ------------------------------------------------------------------ helpers
def test_keyword_overlap() -> None:
    assert keyword_overlap("python sql jobs", "Python and SQL skills") == pytest.approx(2 / 3)
    assert keyword_overlap("", "anything") == 0.0


def test_extract_citations_unique_in_order() -> None:
    assert extract_citations("A [2]. B [1][2]. C [10].") == [2, 1, 10]
    assert extract_citations("no citations") == []


def test_build_context_numbers_and_wraps_sources() -> None:
    chunks = [
        RetrievedChunk(id="1", text="Python needed", source="jd.pdf", page=3, similarity=0.5, score=0.9),
        RetrievedChunk(id="2", text="6-9 LPA", source="notes.txt", page=None, similarity=0.4, score=0.7),
    ]

    context = build_context(chunks)

    assert context.startswith('<untrusted_data source="knowledge_base">')
    assert "[1] (jd.pdf, page 3)\nPython needed" in context
    assert "[2] (notes.txt)\n6-9 LPA" in context


# --------------------------------------------------------------- reranking
def hit(i: str, text: str, similarity: float, source: str = "doc.txt") -> VectorHit:
    return VectorHit(id=i, text=text, metadata={"source": source, "page": 0}, similarity=similarity)


def kb_with_hits(hits: list[VectorHit], reranker: str = "hybrid") -> tuple[KnowledgeBase, VectorStore]:
    store = create_autospec(VectorStore, instance=True)
    store.embedder = LocalEmbedder()  # floor 0.16 / strong 0.60; relevance() needs no model
    store.query.return_value = hits
    ingestor = create_autospec(DocumentIngestor, instance=True)
    ingestor.collection = "documents"
    return KnowledgeBase(store, ingestor, top_k=2, candidates=10, reranker=reranker), store


async def test_candidates_below_the_floor_are_dropped() -> None:
    kb, _ = kb_with_hits([hit("a", "cricket scores", 0.15), hit("b", "weather", 0.05)])

    assert await kb.search("python jobs") == []  # nothing relevant -> empty, not junk


async def test_hybrid_rerank_rewards_exact_keywords() -> None:
    kb, store = kb_with_hits(
        [
            hit("vague", "general career advice for engineers", 0.42),
            hit("exact", "FastAPI and Docker required", 0.38),  # slightly less similar...
        ]
    )

    results = await kb.search("FastAPI Docker")

    assert results[0].id == "exact"  # ...but its keywords win the rerank
    store.query.assert_awaited_once_with("documents", "FastAPI Docker", n_results=10)


async def test_no_reranker_keeps_vector_order() -> None:
    kb, _ = kb_with_hits(
        [hit("vague", "general career advice", 0.42), hit("exact", "FastAPI and Docker required", 0.38)],
        reranker="none",
    )

    assert [c.id for c in await kb.search("FastAPI Docker")] == ["vague", "exact"]


async def test_near_duplicate_chunks_are_removed() -> None:
    text = "AI engineers need Python, SQL and LLM API experience for this role"
    kb, _ = kb_with_hits(
        [hit("a", text, 0.55), hit("b", text + " today", 0.54), hit("c", "Salary is 6-9 LPA", 0.30)]
    )

    assert [c.id for c in await kb.search("python skills")] == ["a", "c"]  # b duplicated a


async def test_llm_reranker_uses_llm_scores(mock_llm) -> None:
    kb, _ = kb_with_hits(
        [hit("a", "general text", 0.50), hit("b", "the precise answer", 0.30)], reranker="llm"
    )
    mock_llm.structured.return_value = _RerankResult(
        scores=[_PassageScore(index=0, score=2), _PassageScore(index=1, score=9)]
    )

    results = await kb.search("question", llm=mock_llm)

    assert [c.id for c in results] == ["b", "a"]
    assert results[0].score == pytest.approx(0.9)
    sent = mock_llm.structured.await_args.args[0][-1].content
    assert "<untrusted_data" in sent  # candidate passages are marked untrusted


async def test_llm_reranker_falls_back_on_failure(mock_llm) -> None:
    kb, _ = kb_with_hits([hit("a", "x", 0.30), hit("b", "y", 0.50)], reranker="llm")
    mock_llm.structured.side_effect = LLMError("down")

    assert [c.id for c in await kb.search("q", llm=mock_llm)] == ["b", "a"]  # vector order


# ----------------------------------------------------------------- answering
async def test_no_relevant_chunks_means_no_llm_call(mock_llm) -> None:
    kb, _ = kb_with_hits([hit("a", "unrelated", 0.05)])

    answer = await kb.answer("What is the capital of France?", mock_llm)

    assert answer.answer == NO_RESULTS_ANSWER and answer.sources == []
    mock_llm.generate.assert_not_awaited()  # no chance to hallucinate


async def test_answer_checks_citations(mock_llm) -> None:
    kb, _ = kb_with_hits([hit("a", "Python and SQL required", 0.55), hit("b", "Salary 6-9 LPA", 0.45)])
    mock_llm.generate.return_value = "Needs Python [1]. Pays 6-9 LPA [2]. Also remote [7]."

    answer = await kb.answer("skills and salary?", mock_llm)

    assert answer.cited == [1, 2]
    assert answer.invalid_citations == [7]  # the model cited a source that doesn't exist
    prompt = mock_llm.generate.await_args.args[0]
    assert "[1] (doc.txt)" in prompt[-1].content and "skills and salary?" in prompt[-1].content


# ------------------------------------------------------------- end-to-end
async def test_end_to_end_ingest_then_search(tmp_path: Path) -> None:
    (tmp_path / "jobs.txt").write_text("AI engineer role needs Python, SQL and FastAPI.", encoding="utf-8")
    (tmp_path / "food.txt").write_text("The cafeteria serves dosa and idli for breakfast.", encoding="utf-8")
    store = VectorStore(make_chroma_client(None), make_embedder_mock())
    ingestor = DocumentIngestor(store, tmp_path, collection=f"t_{uuid.uuid4().hex[:10]}")
    kb = KnowledgeBase(store, ingestor, top_k=1)
    await ingestor.ingest_all()

    results = await kb.search("Which skills: Python SQL FastAPI?")

    assert [c.source for c in results] == ["jobs.txt"]


# ---------------------------------------------------------------- the tool
async def test_knowledge_tool_formats_numbered_untrusted_passages() -> None:
    kb = create_autospec(KnowledgeBase, instance=True)
    kb.search.return_value = [
        RetrievedChunk(id="1", text="Python needed", source="jd.pdf", page=2, similarity=0.5, score=0.81)
    ]

    output = await SearchKnowledgeBaseTool(kb).run(KnowledgeSearchInput(query="skills", k=3))

    kb.search.assert_awaited_once_with("skills", k=3)
    assert output.startswith('<untrusted_data source="knowledge_base">')
    assert "[1] (jd.pdf, page 2, relevance 0.81)\nPython needed" in output


async def test_knowledge_tool_reports_no_results() -> None:
    kb = create_autospec(KnowledgeBase, instance=True)
    kb.search.return_value = []

    output = await SearchKnowledgeBaseTool(kb).run(KnowledgeSearchInput(query="zzz"))

    assert "No relevant passages" in output
