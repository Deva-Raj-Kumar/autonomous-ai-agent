"""Load test against a RUNNING server: many simulated users, real HTTP, real numbers.

    python scripts/load_test.py --url http://127.0.0.1:8000 --users 20 --seconds 30

Each virtual user registers its own account (load-test-<n>-<random>@example.com), logs
in once, then loops over typical dashboard reads for --seconds. The report shows
throughput, latency percentiles per endpoint, and errors.

Run it against a local or staging server, never production: it creates accounts.
It does not start agent runs (that would spend LLM quota); see --with-runs.
"""

import argparse
import asyncio
import secrets
import statistics
import time
from collections import defaultdict

import httpx

PASSWORD = "load test passphrase " + secrets.token_hex(4)
READS = ["/auth/me", "/agent/runs?limit=15", "/approvals?status=pending", "/memories?limit=100"]


class Stats:
    def __init__(self) -> None:
        self.latency_ms: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)

    def record(self, name: str, started: float, response: httpx.Response | None) -> None:
        self.latency_ms[name].append((time.perf_counter() - started) * 1000)
        if response is None or response.status_code >= 400:
            self.errors[name] += 1


async def virtual_user(client: httpx.AsyncClient, number: int, deadline: float, stats: Stats, with_runs: bool) -> None:
    email = f"load-test-{number}-{secrets.token_hex(3)}@example.com"
    await client.post("/auth/register", json={"email": email, "username": f"load{number}", "password": PASSWORD})
    started = time.perf_counter()
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    stats.record("POST /auth/login", started, login)
    if login.status_code != 200:
        return
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post("/memories", headers=headers, json={"content": f"Load test user {number} likes testing"})
    if with_runs:
        await client.post("/agent/runs", headers=headers, json={"goal": "Calculate the average of 4, 8 and 15"})

    step = 0
    while time.perf_counter() < deadline:
        path = READS[step % len(READS)]
        step += 1
        started = time.perf_counter()
        try:
            response = await client.get(path, headers=headers)
        except httpx.HTTPError:
            response = None
        stats.record(f"GET {path.split('?')[0]}", started, response)


def percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--with-runs", action="store_true", help="each user also starts ONE agent run (uses LLM quota)")
    args = parser.parse_args()

    stats = Stats()
    limits = httpx.Limits(max_connections=args.users * 2)
    async with httpx.AsyncClient(base_url=args.url, timeout=30, limits=limits) as client:
        if (await client.get("/health")).status_code != 200:
            raise SystemExit(f"No healthy server at {args.url}")
        started = time.perf_counter()
        deadline = started + args.seconds
        await asyncio.gather(*(virtual_user(client, n, deadline, stats, args.with_runs) for n in range(args.users)))
        elapsed = time.perf_counter() - started

    total = sum(len(v) for v in stats.latency_ms.values())
    errors = sum(stats.errors.values())
    print(f"\n{args.users} users, {elapsed:.1f}s, {total} requests, {total / elapsed:.1f} req/s, "
          f"errors: {errors} ({100 * errors / max(total, 1):.2f}%)\n")
    print(f"{'endpoint':<26}{'count':>7}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'errors':>8}")
    for name, samples in sorted(stats.latency_ms.items()):
        print(f"{name:<26}{len(samples):>7}{statistics.median(samples):>9.1f}"
              f"{percentile(samples, 0.95):>9.1f}{percentile(samples, 0.99):>9.1f}{stats.errors[name]:>8}")


if __name__ == "__main__":
    asyncio.run(main())
