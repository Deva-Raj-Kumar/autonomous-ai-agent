"""Permission policy: ONE place that decides whether a tool call may run.

The ToolRegistry calls PermissionPolicy.authorize() for every call, after argument
validation and before the tool runs. Checks, in order:
  1. disabled tools        - an admin switched the tool off (DISABLED_TOOLS)
  2. argument rules        - per-tool rules on the actual arguments:
                               * send_email: every recipient must be on the allowlist
                               * outbound tools: no secrets in what leaves the machine
                                 (a search query or email is visible to someone else)
  3. per-run budget        - e.g. at most 3 python_exec calls in one run
  4. rate limit            - e.g. at most 20 web searches per minute, across all runs

Everything here is deterministic code: the LLM cannot argue with it. Budgets and rate
limits live in memory (reset on restart), which is fine for one process; a multi-server
deployment would keep them in Redis (Phase 15).
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.config import Settings
from app.safety.secrets import contains_secret

RATE_WINDOW_SECONDS = 60.0
# Tools whose arguments leave the machine: secrets must never be inside them.
OUTBOUND_TOOLS = frozenset({"web_search", "send_email", "python_exec"})


@dataclass
class PermissionResult:
    allowed: bool
    reason: str = ""
    retryable: bool = False  # True for rate limits: waiting can fix it; never for policy denials

    @classmethod
    def allow(cls) -> "PermissionResult":
        return cls(allowed=True)


def recipient_allowed(address: str, allowlist: list[str]) -> bool:
    """Exact address match, wildcard '*', or a domain entry like '@college.edu'. Case-insensitive."""
    address = address.strip().lower()
    for entry in (e.strip().lower() for e in allowlist):
        if entry in ("*", "all"):
            return True
        if entry.startswith("@") and address.endswith(entry):
            return True
        if address == entry:
            return True
    return False


class PermissionPolicy:
    def __init__(
        self,
        *,
        disabled_tools: list[str] | None = None,
        email_allowed_recipients: list[str] | None = None,
        rate_limits_per_minute: dict[str, int] | None = None,
        budgets_per_run: dict[str, int] | None = None,
        clock: Callable[[], float] = time.monotonic,  # injectable, so tests can control time
    ) -> None:
        self._disabled = set(disabled_tools or [])
        self._recipients = list(email_allowed_recipients or [])
        self._rate_limits = dict(rate_limits_per_minute or {})
        self._budgets = dict(budgets_per_run or {})
        self._clock = clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)  # tool -> recent call times
        self._run_counts: dict[tuple[str, str], int] = defaultdict(int)  # (run_id, tool) -> calls

    @classmethod
    def from_settings(cls, settings: Settings) -> "PermissionPolicy":
        return cls(
            disabled_tools=settings.disabled_tools,
            email_allowed_recipients=settings.email_allowed_recipients,
            rate_limits_per_minute=settings.tool_rate_limits_per_minute,
            budgets_per_run=settings.tool_budgets_per_run,
        )

    def authorize(self, tool: str, args: BaseModel, *, run_id: str | None = None) -> PermissionResult:
        """Check every rule; if allowed, COUNT the call (budget + rate). Check-and-count is
        one step, so two concurrent calls can't both squeeze into the last slot."""
        if tool in self._disabled:
            return PermissionResult(False, f"Permission denied: tool '{tool}' is disabled by the administrator.")

        verdict = self._check_arguments(tool, args)
        if not verdict.allowed:
            return verdict

        budget = self._budgets.get(tool)
        if run_id is not None and budget is not None and self._run_counts[(run_id, tool)] >= budget:
            return PermissionResult(False, f"Permission denied: '{tool}' budget of {budget} calls per run is used up.")

        limit = self._rate_limits.get(tool)
        now = self._clock()
        calls = self._calls[tool]
        while calls and now - calls[0] >= RATE_WINDOW_SECONDS:  # forget calls older than the window
            calls.popleft()
        if limit is not None and len(calls) >= limit:
            wait = RATE_WINDOW_SECONDS - (now - calls[0])
            return PermissionResult(False, f"Rate limit: '{tool}' allows {limit} calls per minute; retry in {wait:.0f}s.",
                                    retryable=True)

        calls.append(now)
        if run_id is not None:
            self._run_counts[(run_id, tool)] += 1
        return PermissionResult.allow()

    def _check_arguments(self, tool: str, args: BaseModel) -> PermissionResult:
        if tool == "send_email":
            recipients = getattr(args, "to", [])
            blocked = [r for r in recipients if not recipient_allowed(r, self._recipients)]
            if blocked:
                hint = "" if self._recipients else " (EMAIL_ALLOWED_RECIPIENTS is empty: no recipient is allowed)"
                listed = ", ".join(blocked)
                return PermissionResult(False, f"Permission denied: recipient(s) not on the allowlist: {listed}{hint}.")
        if tool in OUTBOUND_TOOLS:
            for name, value in args.model_dump().items():
                text = " ".join(value) if isinstance(value, list) else str(value)
                if contains_secret(text):
                    return PermissionResult(
                        False, f"Permission denied: argument '{name}' contains what looks like a secret; "
                               f"it must not leave this machine via {tool}.",
                    )
        return PermissionResult.allow()

    def forget_run(self, run_id: str) -> None:
        """Drop a finished run's budget counters (keeps memory bounded)."""
        for key in [k for k in self._run_counts if k[0] == run_id]:
            del self._run_counts[key]
