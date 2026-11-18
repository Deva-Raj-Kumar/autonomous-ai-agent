"""Command-line playground. Run from the project root:

    python -m app.cli models                      # which models can my key use?
    python -m app.cli chat "Explain RAG simply"
    python -m app.cli goal "Research AI fresher jobs in Bengaluru and write a report"
    python -m app.cli plan "Compare AI fresher jobs in Bengaluru and Hyderabad and save a report"

    python -m app.cli list-tools                  # tools and whether they're available
    python -m app.cli tool calculator expression="(45000 + 52000) / 2"
    python -m app.cli tool read_file path=sample_job_description.txt
    python -m app.cli tool python_exec code="print(2**10)" --approve
    python -m app.cli tools "Search the web for AI fresher salaries in Hyderabad and average 6 and 9"

    python -m app.cli talk "I'm Ravi and I want to become an LLM engineer" --session ravi
    python -m app.cli repl --session ravi         # interactive chat with memory (type 'exit')
    python -m app.cli memories                    # list everything remembered
    python -m app.cli memories search city        # which memories would be recalled?
    python -m app.cli memories add "User prefers remote jobs"
    python -m app.cli memories delete 3

    python -m app.cli kb ingest                   # index everything in data/documents
    python -m app.cli kb list                     # what's in the knowledge base
    python -m app.cli kb search "required skills" # see retrieved chunks + scores
    python -m app.cli kb ask "What salary does the AI engineer job offer?"
    python -m app.cli kb delete resume.pdf

    python -m app.cli run "Compare AI fresher jobs in Bengaluru and Hyderabad and write a report"
    python -m app.cli runs                        # recent runs (they survive restarts)
    python -m app.cli show <run_id>
    python -m app.cli approve <run_id> t2          # approve task t2; tasks not listed are rejected
    python -m app.cli continue <run_id>            # resume a run interrupted mid-way
    python -m app.cli history <run_id>             # steps + every tool call, from the database
    python -m app.cli db                           # database + migration status

    python -m app.cli users create you@example.com yourname --admin --adopt-local
    python -m app.cli users list                   # accounts (API logins)
    python -m app.cli users disable someone@example.com   # also ends their sessions
"""

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.planner import Planner
from app.agent.schemas import ExecutionEvent, PlanningResult
from app.agent.workflow import AgentWorkflow, ApprovalDecision, RunView
from app.config import DATA_DIR, get_settings
from app.database.connection import Database, open_database
from app.database.crud import RunRepository
from app.llm.client import LLMError
from app.llm.service import LLMService
from app.logging_config import setup_logging
from app.memory.long_term import LongTermMemory, MemoryRejected
from app.memory.manager import MemoryManager
from app.memory.schemas import ChatTurn
from app.memory.short_term import ConversationStore
from app.memory.vector_store import MemoryVectorIndex, VectorStore, build_vector_store
from app.rag.retrieval import KnowledgeBase, build_knowledge_base
from app.safety.approval import ApprovalStore
from app.tools.registry import ToolRegistry, build_default_registry


def list_models() -> None:
    """Print the Gemini models that support text generation for this API key."""
    settings = get_settings()
    if settings.google_api_key is None:
        sys.exit("GOOGLE_API_KEY is not set in .env")
    from google import genai  # imported here so other commands don't need it

    client = genai.Client(api_key=settings.google_api_key.get_secret_value())
    names = sorted(
        m.name.removeprefix("models/")
        for m in client.models.list()
        if "generateContent" in (m.supported_actions or [])
    )
    print("\n".join(names))
    print(f"\nConfigured GEMINI_MODEL: {settings.gemini_model}")
    print("Note: a model can still appear here after it is retired. Test it with the 'chat' command.")


def make_registry() -> ToolRegistry:
    settings = get_settings()
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    llm_factory = (lambda: LLMService.from_settings(settings)) if settings.llm_api_key_configured else None
    return build_default_registry(
        settings, open_database(settings.database_url), make_knowledge_base(), llm_factory=llm_factory
    )


def parse_tool_arguments(pairs: list[str]) -> dict[str, Any]:
    """Turn ["expression=2+2", "max_results=3"] into {"expression": "2+2", "max_results": 3}.

    Values that look like JSON (numbers, true/false, lists) are converted; others stay text.
    """
    arguments: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"Tool arguments must look like key=value, got: {pair!r}")
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    return arguments


def print_plan(result: PlanningResult) -> None:
    """Pretty-print a planning result (ASCII only, so any Windows terminal can show it)."""
    if result.status == "needs_clarification":
        print("The goal is not clear enough yet. Please answer:")
        for question in result.clarifying_questions:
            print(f"  - {question}")
        return

    plan = result.plan
    if plan is None:  # not `assert`: python -O would remove it
        raise SystemExit("Planner returned no plan.")
    print(f"Strategy: {plan.strategy}\n")
    print(f"Tasks ({len(plan.tasks)}), drafted in {result.attempts} attempt(s):")
    for task in plan.tasks:
        needs = f"  needs: {', '.join(task.depends_on)}" if task.depends_on else ""
        approval = "  [APPROVAL REQUIRED]" if task.requires_approval else ""
        print(f"  {task.id:<4} {task.priority:<6} {task.tool:<22} {task.title}{needs}{approval}")
        print(f"       -> expect: {task.expected_output}")
    print("\nExecution order: " + " -> ".join(plan.execution_order))
    waves = " -> ".join("[" + ", ".join(group) + "]" for group in plan.parallel_groups)
    print(f"Parallel waves:  {waves}")


def require_database() -> Database:
    settings = get_settings()
    database = open_database(settings.database_url, auto_migrate=settings.db_auto_migrate)
    if database is None:
        raise SystemExit(
            "Memory needs a working database. Fix DATABASE_URL in .env, or remove it "
            "to use the default SQLite file (data/agent.db)."
        )
    return database


_vector_store: VectorStore | None = None


def vector_store() -> VectorStore:
    """One shared vector store per CLI run (creating it twice would load the model twice)."""
    global _vector_store
    if _vector_store is None:
        _vector_store = build_vector_store(get_settings())
    return _vector_store


def make_long_term(database: Database) -> LongTermMemory:
    index = MemoryVectorIndex(vector_store()) if get_settings().memory_semantic_search else None
    return LongTermMemory(database, index)


def make_knowledge_base() -> KnowledgeBase:
    settings = get_settings()
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    return build_knowledge_base(settings, vector_store())


async def run_kb(words: list[str]) -> None:
    action, rest = (words[0], " ".join(words[1:])) if words else ("list", "")
    kb = make_knowledge_base()
    if action == "ingest":
        for r in await kb.ingestor.ingest_all() or []:
            detail = f" ({r.detail})" if r.detail else ""
            print(f"  {r.status:<10} {r.source}: {r.chunks} chunks{detail}")
        if not (get_settings().documents_dir.is_dir() and any(get_settings().documents_dir.iterdir())):
            print(f"No files yet. Put PDF/DOCX/TXT/MD files in {get_settings().documents_dir}")
    elif action == "list":
        docs = await kb.ingestor.list_documents()
        if not docs:
            print("Knowledge base is empty. Run: python -m app.cli kb ingest")
        for d in docs:
            pages = f", pages {d.pages[0]}-{d.pages[-1]}" if d.pages else ""
            print(f"  {d.source}: {d.chunks} chunks{pages} (ingested {d.ingested_at})")
    elif action == "search" and rest:
        chunks = await kb.search(rest)
        if not chunks:
            print("No relevant chunks found.")
        for n, c in enumerate(chunks, start=1):
            print(f"[{n}] score={c.score:.2f} similarity={c.similarity:.2f} ({c.citation_label})")
            print("    " + " ".join(c.text.split())[:240])
    elif action == "ask" and rest:
        answer = await kb.answer(rest, LLMService.from_settings())
        print(f"\n{answer.answer.strip()}\n")
        for n, c in enumerate(answer.sources, start=1):
            mark = "*" if n in answer.cited else " "
            print(f"  {mark}[{n}] {c.citation_label} (score {c.score:.2f})")
        if answer.invalid_citations:
            print(f"  WARNING: answer cites sources that don't exist: {answer.invalid_citations}")
    elif action == "delete" and rest:
        removed = await kb.ingestor.delete_document(rest)
        print(f"Removed {removed} chunks." if removed else "No such document in the knowledge base.")
    else:
        raise SystemExit("Usage: kb [ingest | list | search <text> | ask <question> | delete <source>]")


def print_event(event: ExecutionEvent) -> None:
    """Live progress line for each executor event."""
    icons = {"run_started": ">>", "task_started": "..", "task_finished": "ok", "task_skipped": "--", "run_finished": "<<"}
    icon = "!!" if "failed" in event.message else icons.get(event.kind, "  ")
    print(f"  [{icon}] {event.task_id or '':<4} {event.message}", flush=True)


def print_run(view: RunView) -> None:
    """Summary of a run's latest checkpoint: status, tasks, approvals, report."""
    print(f"\nRun {view.run_id}  |  status: {view.status}  |  steps: {view.steps_used}")
    if view.stop_reason:
        print(f"Stopped: {view.stop_reason}")
    for ev in view.evaluation_history:  # every evaluation round, in order
        checked = sum(e["checked"] for e in ev.get("evidence", []))
        unsupported = sum(len(e["unsupported"]) for e in ev.get("evidence", []))
        quality = f"quality {ev['quality_score']}/10, " if ev.get("quality_score") is not None else ""
        evidence = f"evidence {checked - unsupported}/{checked} facts verified" if checked else "no facts to verify"
        print(f"Evaluation: {ev['verdict']} ({ev['mode']}; {quality}{evidence}) - {ev['reason']}")
        for task_id, note in ev.get("feedback", {}).items():
            print(f"    -> {task_id} sent back: {note[:160]}")
    if view.error:
        print(f"Error: {view.error}")
    if view.status == "needs_clarification" and view.planning:
        print("The goal is not clear enough yet. Please answer:")
        for question in view.planning.get("clarifying_questions", []):
            print(f"  - {question}")
    for task in (view.plan or {}).get("tasks", []):
        attempts = f" (attempts: {task['attempts']})" if task.get("attempts", 0) > 1 else ""
        problem = f" - {task['error']}" if task.get("error") and task["status"] != "completed" else ""
        print(f"  {task['id']:<4} {task['status']:<17} {task['tool']:<22}{attempts}{problem}")
    if view.pending_approvals:
        print("\nWaiting for your approval:")
        for task in view.pending_approvals:
            print(f"  {task['id']}: {task['title']} ({task['tool']})\n      {task['description']}")
            # APPROVE WHAT YOU SEE: print the exact arguments that will run.
            for name, value in (task.get("arguments") or {}).items():
                shown = value if isinstance(value, str) else json.dumps(value)
                indented = shown.replace("\n", "\n          ")
                print(f"      {name}: {indented}")
        ids = " ".join(t["id"] for t in view.pending_approvals)
        print(f"\nApprove:  python -m app.cli approve {view.run_id} {ids}")
        print(f"Reject:   python -m app.cli approve {view.run_id}      (no ids = reject all)")
    if view.resumable:
        print(f"\nInterrupted at {view.next_nodes}. Resume: python -m app.cli continue {view.run_id}")
    if view.final_output:
        reports = DATA_DIR / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        path = reports / f"run_{view.run_id[:8]}.md"
        path.write_text(view.final_output, encoding="utf-8")
        print(f"\n{'=' * 70}\n{view.final_output}\n{'=' * 70}\nSaved to {path}")


@asynccontextmanager
async def open_workflow(on_event=None) -> AsyncIterator[AgentWorkflow]:
    """The same checkpoint file as the API, so CLI and API see the same runs."""
    settings = get_settings()
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    llm = LLMService.from_settings(settings)
    database = open_database(settings.database_url, auto_migrate=settings.db_auto_migrate)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as checkpointer:
        yield AgentWorkflow(
            llm_factory=lambda: llm, registry=make_registry(), settings=settings,
            checkpointer=checkpointer, on_event=on_event,
            approval_store=ApprovalStore(database) if database is not None else None,
            run_repository=RunRepository(database) if database is not None else None,
        )


async def run_workflow_command(command: str, words: list[str]) -> None:
    async with open_workflow(on_event=print_event) as workflow:
        if command == "run":
            if not words:
                raise SystemExit('Usage: run "<goal>"')
            print("Planning and executing (one checkpoint per step)...", flush=True)
            run_id = await workflow.start(" ".join(words))
        elif command == "runs":
            for v in await workflow.list_runs():
                flag = " [resumable]" if v.resumable else ""
                print(f"  {v.run_id}  {v.created_at}  {v.status:<17} {v.goal[:60]}{flag}")
            return
        elif command in {"show", "approve", "continue"} and words:
            run_id = words[0]
            view = await workflow.get(run_id)
            if view is None:
                raise SystemExit(f"No run with id {run_id}")
            if command == "approve":
                if not view.pending_approvals:
                    raise SystemExit("This run is not waiting for approval.")
                await workflow.approve(run_id, ApprovalDecision(approved=words[1:], decided_by="cli"))
            elif command == "continue":
                if not view.resumable:
                    raise SystemExit("This run is finished or waiting for approval: nothing to continue.")
                await workflow.continue_run(run_id)
        else:
            raise SystemExit(f"Usage: {command} <run_id>" + (" [task ids to approve]" if command == "approve" else ""))
        print_run(await workflow.get(run_id))


def db_status() -> None:
    """Which database, is it reachable, and is the schema at the latest migration?
    Prints facts only, never the URL (it contains a password)."""
    from app.database.connection import Database
    from app.database.migrations import current_revision, head_revision

    settings = get_settings()
    try:
        database = Database(settings.database_url)
        current = current_revision(database.engine)
    except Exception as exc:  # noqa: BLE001 - report any connection problem plainly
        raise SystemExit(f"Database not reachable: {type(exc).__name__}") from None
    head = head_revision()
    print(f"database: {database.dialect} | host: {database.url.host or '-'} | name: {database.url.database}")
    print(f"schema revision: {current}  (code expects: {head})")
    if current == head:
        print("OK: schema is up to date.")
    elif database.in_memory:
        print("In-memory database: tables come from the models (tests).")
    else:
        print("ACTION NEEDED: run  alembic upgrade head")


def print_history(history) -> None:
    run = history.run
    quality = f" | quality {run.quality_score}/10" if run.quality_score is not None else ""
    print(f"Run {run.run_id} | {run.status} | steps {run.steps_used}{quality}\nGoal: {run.goal}\n")
    print("Plan steps:")
    for step in history.steps:
        attempts = f" (attempts: {step.attempts})" if step.attempts > 1 else ""
        print(f"  {step.step_number}. {step.step_key or '-':<4} {step.status or '-':<17} "
              f"{step.tool_name or '-':<22} {step.title or ''}{attempts}")
    print(f"\nTool calls ({len(history.tool_logs)}):")
    for log in history.tool_logs:
        flags = log.output_data.get("security_flags") if log.output_data else None
        flag_note = f"  SECURITY FLAGS: {', '.join(flags)}" if flags else ""
        error = f"  error: {log.error[:80]}" if log.error else ""
        print(f"  {log.step_key or '-':<4} #{log.attempt} {log.tool_name or '-':<22} {log.status or '-':<14} "
              f"{log.execution_time_ms or 0:>6} ms{error}{flag_note}")


def make_memory_manager() -> MemoryManager:
    database = require_database()
    return MemoryManager(
        LLMService.from_settings(), ConversationStore(database), make_long_term(database)
    )


def print_turn(turn: ChatTurn, verbose: bool = True) -> None:
    print(f"\nassistant> {turn.reply}\n")
    if verbose:
        if turn.memories_used:
            print("  (recalled: " + "; ".join(m.content for m in turn.memories_used) + ")")
        for c in turn.memory_changes:
            state = "saved" if c.applied else f"skipped: {c.reason}"
            print(f"  (memory {c.action} #{c.memory_id}: {c.content!r} -> {state})")
        if turn.summarized:
            print("  (older messages were folded into the conversation summary)")


async def run_memories(words: list[str]) -> None:
    memory = make_long_term(require_database())
    action = words[0] if words else "list"
    if action == "list":
        records = await memory.list_memories()
        if not records:
            print("No memories yet. Chat with: python -m app.cli talk \"...\"")
        for m in records:
            print(f"  #{m.id:<3} [{m.category}, importance {m.importance}] {m.content}")
    elif action == "search":
        for s in await memory.search(" ".join(words[1:]), limit=10, mark_accessed=False):
            print(f"  score={s.score:.2f} (relevance={s.relevance:.2f}, recency={s.recency:.2f})  "
                  f"#{s.memory.id} {s.memory.content}")
    elif action == "add":
        try:
            record, created = await memory.add(" ".join(words[1:]), source="manual")
        except MemoryRejected as exc:
            raise SystemExit(f"Rejected: {exc}") from exc
        print(f"{'Added' if created else 'Already known (refreshed)'}: #{record.id} {record.content}")
    elif action == "delete" and len(words) == 2 and words[1].isdigit():
        print("Deleted." if await memory.delete(int(words[1])) else "No memory with that id.")
    else:
        raise SystemExit("Usage: memories [list | search <text> | add <text> | delete <id>]")


async def repl(session_id: str) -> None:
    """Interactive chat loop. input() blocks, which is fine in a terminal program."""
    manager = make_memory_manager()
    print(f"Chatting in session '{session_id}'. Type 'exit' to quit.")
    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"exit", "quit"}:
            break
        if message:
            print_turn(await manager.chat(message, session_id))


USERS_USAGE = """Usage:
  users list
  users create <email> <username> [--admin] [--adopt-local]
  users promote|demote|disable|enable <email>"""


async def users_command(words: list[str], *, make_admin: bool, adopt_local: bool) -> None:
    """Account administration from the server's own terminal (no API token needed:
    whoever can run this can already read the database)."""
    from getpass import getpass

    from app.auth.security import TokenConfig, password_problem
    from app.auth.service import AuthService, EmailAlreadyRegistered

    if not words:
        raise SystemExit(USERS_USAGE)
    # These commands issue no tokens, so the signing secret is irrelevant here.
    service = AuthService(require_database(), TokenConfig(secret="unused-by-cli-admin-commands"))  # noqa: S106  # nosec B106
    action, rest = words[0], words[1:]
    if action == "list":
        for u in service.list_users():
            flags = ", ".join(f for f, on in (("admin", u.is_admin), ("disabled", not u.is_active)) if on)
            print(f"{u.id:>4}  {u.email:<35} {u.username:<20} {flags}")
        return
    if action == "create" and len(rest) == 2:
        email, username = rest
        # getpass: typed password isn't echoed, and never lands in shell history.
        password = getpass("Password (10+ characters): ")
        if password != getpass("Repeat password: "):
            raise SystemExit("Passwords don't match.")
        problem = password_problem(password, email, username)
        if problem:
            raise SystemExit(problem)
        try:
            user = await service.register(email, username, password, is_admin=make_admin)
        except EmailAlreadyRegistered:
            raise SystemExit("An account with this email already exists.") from None
        print(f"Created user #{user.id} {user.email}" + (" (admin)" if user.is_admin else ""))
        if adopt_local:
            moved = service.adopt_local_data(user.id)
            print("Moved the CLI's local data to this account: " + ", ".join(f"{k} {v}" for k, v in moved.items()))
        return
    flags = {"promote": {"is_admin": True}, "demote": {"is_admin": False},
             "disable": {"is_active": False}, "enable": {"is_active": True}}
    if action in flags and len(rest) == 1:
        user = service.set_flags(rest[0], **flags[action])
        if user is None:
            raise SystemExit("No user with that email.")
        print(f"{action}d: {user.email}" + ("  (all sessions ended)" if action == "disable" else ""))
        return
    raise SystemExit(USERS_USAGE)


async def run(command: str, words: list[str], approve: bool, session: str | None = None,
              make_admin: bool = False, adopt_local: bool = False) -> None:
    text = " ".join(words)

    if command == "users":
        await users_command(words, make_admin=make_admin, adopt_local=adopt_local)
        return
    if command == "db":
        db_status()
        return
    if command == "history":
        if not words:
            raise SystemExit("Usage: history <run_id>")
        history = await RunRepository(require_database()).history(words[0])
        if history is None:
            raise SystemExit("No history for that run id.")
        print_history(history)
        return
    if command in {"run", "runs", "show", "approve", "continue"}:
        await run_workflow_command(command, words)
        return
    if command == "kb":
        await run_kb(words)
        return
    if command == "memories":
        await run_memories(words)
        return
    if command == "repl":
        await repl(session or "cli")
        return

    if command == "list-tools":
        for tool in make_registry().describe():
            state = "available" if tool["available"] else "not yet available"
            approval = ", needs approval" if tool["requires_approval"] else ""
            print(f"  {tool['name']:<22} {state}{approval}")
        return

    if command == "tool":
        if not words:
            raise SystemExit("Usage: python -m app.cli tool <name> key=value ... [--approve]")
        result = await make_registry().execute(
            words[0], parse_tool_arguments(words[1:]), approved=approve
        )
        print(f"[{result.status.value}] {result.tool_name} in {result.duration_ms:.0f} ms")
        print(result.output if result.ok else result.error)
        return

    if not text:
        raise SystemExit(f"'{command}' needs a text argument")
    if command == "talk":
        print_turn(await make_memory_manager().chat(text, session or "cli"))
        return
    service = LLMService.from_settings()
    if command == "chat":
        print(await service.chat(text))
    elif command == "goal":
        print((await service.analyze_goal(text)).model_dump_json(indent=2))
    elif command == "plan":
        print_plan(await Planner.from_settings(service).create_plan(text))
    elif command == "tools":
        # The LLM chooses among the REAL tools; every call still goes through the registry.
        result = await service.run_with_tools(text, make_registry().as_langchain_tools())
        for call in result.tool_calls:
            print(f"[tool] {call.tool_name}({json.dumps(call.arguments)})")
            print("       " + call.output[:300].replace("\n", "\n       "))
        print(f"\n{result.answer}\n\n(rounds: {result.rounds})")


COMMANDS = [
    "models", "chat", "goal", "plan", "list-tools", "tool", "tools", "talk", "repl", "memories", "kb",
    "run", "runs", "show", "approve", "continue", "history", "db", "users",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Try the agent's building blocks from the terminal.")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("args", nargs="*", help="message/goal text, or: <tool name> key=value ...")
    parser.add_argument("--approve", action="store_true", help="approve a sensitive tool (simulates a human)")
    parser.add_argument("--session", help="chat session id for talk/repl (default: cli)")
    parser.add_argument("--admin", action="store_true", help="users create: make the account an admin")
    parser.add_argument("--adopt-local", action="store_true", help="users create: move the CLI's local data to it")
    args = parser.parse_args()

    setup_logging(get_settings().log_level)
    if args.command == "models":
        list_models()
        return
    try:
        # asyncio.run starts the event loop
        asyncio.run(run(args.command, args.args, args.approve, args.session, args.admin, args.adopt_local))
    except LLMError as exc:
        sys.exit(f"LLM error: {exc}")


if __name__ == "__main__":
    main()
