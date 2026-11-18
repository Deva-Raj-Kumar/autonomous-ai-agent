"""LIVE tests: these call the real LLM API, use your key, and count against your quota.

They are skipped by default. Run them on purpose with (PowerShell):
    $env:RUN_LIVE_TESTS="1"; pytest -m live -v; Remove-Item Env:RUN_LIVE_TESTS
"""

import os

import pytest

from app.config import Settings
from app.llm.example_tools import EXAMPLE_TOOLS
from app.llm.schemas import GoalAnalysis
from app.llm.service import LLMService

pytestmark = [
    pytest.mark.live,
    pytest.mark.anyio,
    pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to run"),
]


@pytest.fixture
def service() -> LLMService:
    settings = Settings()  # reads your real .env
    if not settings.llm_api_key_configured:
        pytest.skip("no API key in .env")
    return LLMService.from_settings(settings)


async def test_live_chat(service: LLMService) -> None:
    reply = await service.chat("Reply with exactly the word: pong")

    assert "pong" in reply.lower()


async def test_live_structured_goal(service: LLMService) -> None:
    result = await service.analyze_goal(
        "Research the top 10 AI Engineer fresher jobs in Bengaluru and Hyderabad, "
        "compare their required skills, generate a report, and save it in the database."
    )

    assert isinstance(result, GoalAnalysis)
    assert "web_search" in result.required_capabilities


async def test_live_tool_calling(service: LLMService) -> None:
    result = await service.run_with_tools("What is 23.5 multiplied by 19? Use a tool.", EXAMPLE_TOOLS)

    assert any(c.tool_name == "multiply_numbers" for c in result.tool_calls)
    assert "446.5" in result.answer


async def test_live_planner_builds_valid_parallel_plan(service: LLMService) -> None:
    from app.agent.planner import Planner

    result = await Planner(service).create_plan(
        "Research the top 10 AI Engineer fresher jobs in Bengaluru and Hyderabad, "
        "compare their required skills, generate a report, and save it in the database."
    )

    assert result.status == "planned"
    plan = result.plan
    tools = [t.tool for t in plan.tasks]
    assert "web_search" in tools and "save_to_database" in tools
    # The two cities should be searched in parallel (first wave has 2+ tasks).
    assert len(plan.parallel_groups[0]) >= 2


async def test_live_planner_flags_email_for_approval(service: LLMService) -> None:
    from app.agent.planner import Planner

    result = await Planner(service).create_plan(
        "Find 3 Python internships in Pune, write a short summary, "
        "and email it to my mentor at mentor@example.com."
    )

    email_tasks = [t for t in result.plan.tasks if t.tool == "send_email"]
    assert email_tasks and all(t.requires_approval for t in email_tasks)


async def test_live_duckduckgo_search() -> None:
    from app.tools.web_search import DuckDuckGoSearchProvider

    hits = await DuckDuckGoSearchProvider().search("Python programming language", 3)

    assert hits and all(h.url.startswith("http") for h in hits)


async def test_live_llm_uses_registry_tools(service: LLMService, tmp_path) -> None:
    from app.config import Settings
    from app.tools.registry import build_default_registry

    registry = build_default_registry(Settings(_env_file=None, documents_dir=tmp_path))
    result = await service.run_with_tools(
        "Use the calculator to compute (45000 + 52000) / 2.", registry.as_langchain_tools()
    )

    assert any(c.tool_name == "calculator" for c in result.tool_calls)
    assert "48500" in result.answer.replace(",", "")


async def test_live_memory_extraction_updates_conflicting_fact(service: LLMService) -> None:
    from app.database.connection import Database
    from app.memory.long_term import LongTermMemory
    from app.memory.manager import MemoryManager
    from app.memory.short_term import ConversationStore

    database = Database("sqlite://")
    database.create_tables()
    manager = MemoryManager(service, ConversationStore(database), LongTermMemory(database))
    await manager.long_term.add("User lives in Pune.", category="profile", importance=4)

    changes = await manager.extract_memories("I just moved to Hyderabad for a new job.", source="test")

    assert any(c.action == "update" and c.applied for c in changes)
    contents = " ".join(m.content for m in await manager.long_term.list_memories())
    assert "Hyderabad" in contents and "Pune" not in contents


async def test_live_local_embedder_semantic_memory() -> None:
    """Real embedding model: 'city' must find 'Hyderabad' with no shared words."""
    import uuid

    from app.database.connection import Database
    from app.memory.long_term import LongTermMemory
    from app.memory.vector_store import MemoryVectorIndex, VectorStore, make_chroma_client
    from app.rag.embeddings import LocalEmbedder

    database = Database("sqlite://")
    database.create_tables()
    store = VectorStore(make_chroma_client(None), LocalEmbedder())
    memory = LongTermMemory(database, MemoryVectorIndex(store, collection=f"live_{uuid.uuid4().hex[:8]}"))
    await memory.add("User lives in Hyderabad.", importance=3)
    await memory.add("User likes cricket.", importance=3)

    results = await memory.search("Which city should I look for jobs in?")

    assert [r.memory.content for r in results] == ["User lives in Hyderabad."]


async def test_live_rag_answer_with_citations(service: LLMService, tmp_path) -> None:
    import uuid

    from app.memory.vector_store import VectorStore, make_chroma_client
    from app.rag.embeddings import LocalEmbedder
    from app.rag.ingestion import DocumentIngestor
    from app.rag.retrieval import KnowledgeBase

    (tmp_path / "policy.txt").write_text("Employees get 24 days of paid leave per year.", encoding="utf-8")
    (tmp_path / "jd.txt").write_text("The AI engineer role pays 6-9 LPA.", encoding="utf-8")
    store = VectorStore(make_chroma_client(None), LocalEmbedder())
    kb = KnowledgeBase(store, DocumentIngestor(store, tmp_path, collection=f"live_{uuid.uuid4().hex[:8]}"))
    await kb.ingestor.ingest_all()

    answer = await kb.answer("How many vacation days do employees get?", service)
    unknown = await kb.answer("What is the capital of France?", service)

    assert "24" in answer.answer and answer.cited and not answer.invalid_citations
    assert unknown.sources == []


async def test_live_autonomous_run_plans_and_executes(service: LLMService, tmp_path) -> None:
    """Goal -> plan -> parallel execution -> report, with real LLM calls (no web, no DB)."""
    import uuid

    from app.agent.executor import TaskExecutor
    from app.agent.planner import Planner
    from app.agent.schemas import ExecutionStatus
    from app.config import Settings
    from app.memory.vector_store import VectorStore, make_chroma_client
    from app.rag.embeddings import LocalEmbedder
    from app.rag.ingestion import DocumentIngestor
    from app.rag.retrieval import KnowledgeBase
    from app.tools.registry import build_default_registry

    (tmp_path / "jd.txt").write_text("The AI engineer job pays 6-9 LPA.", encoding="utf-8")
    (tmp_path / "intern.txt").write_text("The internship stipend is 40,000 INR per month.", encoding="utf-8")
    store = VectorStore(make_chroma_client(None), LocalEmbedder())
    kb = KnowledgeBase(store, DocumentIngestor(store, tmp_path, collection=f"live_{uuid.uuid4().hex[:8]}"))
    await kb.ingestor.ingest_all()
    settings = Settings(documents_dir=tmp_path)
    registry = build_default_registry(settings, None, kb, llm_factory=lambda: service)

    planning = await Planner.from_settings(service, settings, tools=registry.available_specs()).create_plan(
        "Using my knowledge base, convert the internship stipend to LPA per year with the calculator "
        "and say whether it pays more than the AI engineer job."
    )
    result = await TaskExecutor.from_settings(registry, service, settings).execute(planning.plan)

    assert result.status == ExecutionStatus.COMPLETED
    assert {"search_knowledge_base", "calculator"} <= {t.tool for t in result.plan.tasks}
    assert "4.8" in (result.final_output or "")


async def test_live_judge_catches_wrong_location_and_fabricated_facts(service: LLMService) -> None:
    """The flawed run from the Phase 9 live check: Pakistan results + made-up report facts."""
    from app.agent.evaluator import Evaluator, Verdict
    from app.agent.schemas import Plan, Task, TaskStatus
    from tests.test_planner import make_analysis

    def done(task_id, tool, deps, description, expected, result):
        return Task(id=task_id, title=description[:40], description=description, tool=tool, depends_on=deps,
                    priority="high", expected_output=expected, status=TaskStatus.COMPLETED, result=result)

    plan = Plan(goal="Find AI engineer fresher jobs in Hyderabad, India and write a report.",
                analysis=make_analysis(), strategy="s", tasks=[
        done("t1", "web_search", [], "Search AI engineer fresher jobs in Hyderabad, India",
             "AI engineer fresher job postings in Hyderabad, India",
             "1. AI Intern - Karachi Tech, Hyderabad, Sindh, Pakistan. URL: https://pk.indeed.com/job/1"),
        done("t2", "generate_report", ["t1"], "Write the report", "A report on Hyderabad, India jobs",
             "There are 1,250 AI fresher jobs in Hyderabad (https://naukri.example/hyd-ai)."),
    ])

    ev = await Evaluator(service, max_rounds=1).evaluate(plan)

    assert ev.verdict in (Verdict.RETRY_TASKS, Verdict.REPLAN)
    assert {"t1", "t2"} <= set(ev.feedback) or ev.verdict == Verdict.REPLAN
    assert set(ev.evidence[0].unsupported) == {"1,250", "https://naukri.example/hyd-ai"}
