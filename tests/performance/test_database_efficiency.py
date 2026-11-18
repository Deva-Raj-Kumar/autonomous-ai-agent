"""Structural performance tests: they count queries and read query plans instead of
timing things, so they give the same answer on a fast laptop and a slow CI machine.

N+1 queries: listing N rows with 1 query for the list + 1 query PER row. Invisible with
5 rows in development, slow with 5,000 in production. The fix is never "a faster
server": it's a different query."""

import contextlib
import time

import pytest
from sqlalchemy import event, select, text

from app.auth.context import acting_as
from app.database.crud import RunRepository
from app.database.models import AgentRun, Memory
from app.safety.approval import ApprovalStore
from tests.support.stack import sign_up

pytestmark = [pytest.mark.real_auth, pytest.mark.anyio]


@contextlib.contextmanager
def count_queries(engine):
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def seed_memories(database, user_id: int, count: int, start: int = 0) -> None:
    with database.session() as s:  # direct inserts: seeding speed is not what we measure
        s.add_all([Memory(user_id=user_id, content=f"fact number {start + i} about topic {start + i}",
                          category="other", importance=3) for i in range(count)])


async def seed_runs(database, user_id: int, count: int, start: int = 0) -> None:
    repository, store = RunRepository(database), ApprovalStore(database)
    with acting_as(user_id):
        for i in range(start, start + count):
            await repository.create_run(f"run-{i}", f"goal {i}")
            await store.request(f"run-{i}", "t2", "send_email", "Email", {"to": ["m@example.com"], "n": i})


async def test_list_endpoints_use_a_constant_number_of_queries(client) -> None:
    user = sign_up(client, "perf@example.com")
    database = client.app.state.database
    paths = ["/memories?limit=500", "/approvals?limit=500", "/agent/runs?limit=100"]

    seed_memories(database, user.id, 5)
    await seed_runs(database, user.id, 5)
    with count_queries(database.engine) as small:
        for path in paths:
            assert user.get(path).status_code == 200

    seed_memories(database, user.id, 45, start=5)
    await seed_runs(database, user.id, 45, start=5)
    with count_queries(database.engine) as large:
        for path in paths:
            assert user.get(path).status_code == 200

    # 10x the rows, same number of queries: no N+1 anywhere in these endpoints.
    assert len(large) == len(small), f"{len(small)} queries for 5 rows, {len(large)} for 50"


async def test_run_history_is_three_queries_whatever_its_size(client) -> None:
    user = sign_up(client, "perf@example.com")
    run_id = user.start_run("Calculate the average salary and write a report")
    user.wait(run_id)

    with count_queries(client.app.state.database.engine) as statements:
        assert user.get(f"/agent/runs/{run_id}/history").status_code == 200

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 4, selects  # user lookup (auth) + run + steps + tool logs


def plan_of(database, statement) -> str:
    compiled = statement.compile(database.engine, compile_kwargs={"literal_binds": True})
    with database.engine.connect() as conn:
        return " | ".join(row[-1] for row in conn.execute(text(f"EXPLAIN QUERY PLAN {compiled}")))


def test_the_runs_index_query_uses_an_index_and_needs_no_sort(client) -> None:
    database = client.app.state.database
    query = (select(AgentRun).where(AgentRun.user_id == 1, AgentRun.run_id.is_not(None))
             .order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(20))

    plan = plan_of(database, query)

    assert "USING INDEX" in plan, plan
    # "TEMP B-TREE FOR ORDER BY" = read ALL of the user's runs, then sort them, then
    # keep 20. With the right index the rows come out already in order.
    assert "TEMP B-TREE" not in plan, plan


def test_memory_queries_use_the_owner_index(client) -> None:
    database = client.app.state.database

    plan = plan_of(database, select(Memory).where(Memory.user_id == 1))

    assert "USING INDEX" in plan and "SCAN memories" not in plan, plan


async def test_memory_search_scales_to_a_thousand_memories(client) -> None:
    user = sign_up(client, "perf@example.com")
    seed_memories(client.app.state.database, user.id, 1000)

    started = time.perf_counter()
    response = user.get("/memories/search", params={"q": "topic 512", "limit": 5})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200 and response.json()[0]["memory"]["content"].endswith("topic 512")
    assert elapsed < 1.5, f"search over 1000 memories took {elapsed:.2f}s"
