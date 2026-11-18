"""Latency budgets and concurrency, measured in-process (no network).

Budgets are deliberately generous (CI machines are slow and noisy): they catch
regressions of 10x (an accidental N+1, a blocking call on the event loop), not 10%.
For real numbers against a running server, use scripts/load_test.py.
"""

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.performance.test_database_efficiency import seed_memories
from tests.support.stack import sign_up

pytestmark = pytest.mark.real_auth


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


def timed(call) -> float:
    started = time.perf_counter()
    response = call()
    elapsed = (time.perf_counter() - started) * 1000
    assert response.status_code == 200, response.text
    return elapsed


def test_health_check_is_fast(client) -> None:
    samples = [timed(lambda: client.get("/health")) for _ in range(200)]

    assert p95(samples) < 50, f"p95 {p95(samples):.1f} ms"


def test_authenticated_reads_stay_within_budget(client) -> None:
    user = sign_up(client, "perf@example.com")
    seed_memories(client.app.state.database, user.id, 200)

    budgets_ms = {"/auth/me": 60, "/memories?limit=200": 250, "/agent/runs": 150, "/approvals": 150}
    for path, budget in budgets_ms.items():
        samples = [timed(lambda path=path: user.get(path)) for _ in range(40)]
        assert p95(samples) < budget, f"{path}: p95 {p95(samples):.1f} ms > {budget} ms"


def test_concurrent_users_are_served_correctly(client) -> None:
    users = [sign_up(client, f"user{i}@example.com") for i in range(8)]
    for user in users:
        user.post("/memories", json={"content": f"I am user number {user.id}"})

    def session(user) -> list[tuple[int, list[str]]]:
        return [(r.status_code, [m["content"] for m in r.json()])
                for r in (user.get("/memories") for _ in range(15))]

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(session, users))
    elapsed = time.perf_counter() - started

    for user, responses in zip(users, results, strict=True):
        # Under concurrency every answer is still correct AND only that user's data:
        # a mixed-up request context would show up here as someone else's memory.
        assert all(status == 200 for status, _ in responses)
        assert all(contents == [f"I am user number {user.id}"] for _, contents in responses)
    assert elapsed < 15, f"120 concurrent requests took {elapsed:.1f}s"
