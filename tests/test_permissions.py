"""Permission policy tests: unit rules, then enforcement through the real ToolRegistry."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.safety.permissions import PermissionPolicy, recipient_allowed
from app.tools.base import AgentTool, ToolStatus
from app.tools.email_tool import EmailInput
from app.tools.registry import ToolRegistry, build_default_registry
from app.tools.web_search import WebSearchInput

pytestmark = pytest.mark.anyio


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def email(*to: str, body: str = "Hello") -> EmailInput:
    return EmailInput(to=list(to), subject="Report", body=body)


# ------------------------------------------------------------- unit rules
@pytest.mark.parametrize(
    ("address", "allowed"),
    [("mentor@example.com", True), ("MENTOR@Example.com", True), ("prof@college.edu", True),
     ("attacker@evil.com", False), ("mentor@example.com.evil.com", False), ("x@notcollege.edu", False)],
)
def test_recipient_allowlist(address: str, allowed: bool) -> None:
    assert recipient_allowed(address, ["mentor@example.com", "@college.edu"]) is allowed


def test_disabled_tool_is_denied() -> None:
    result = PermissionPolicy(disabled_tools=["web_search"]).authorize("web_search", WebSearchInput(query="ai jobs"))

    assert not result.allowed and "disabled" in result.reason


def test_email_to_unknown_recipient_is_denied() -> None:
    policy = PermissionPolicy(email_allowed_recipients=["mentor@example.com"])

    assert policy.authorize("send_email", email("mentor@example.com")).allowed
    denied = policy.authorize("send_email", email("mentor@example.com", "attacker@evil.com"))
    assert not denied.allowed and "attacker@evil.com" in denied.reason


def test_empty_allowlist_denies_every_email() -> None:
    result = PermissionPolicy().authorize("send_email", email("anyone@example.com"))

    assert not result.allowed and "EMAIL_ALLOWED_RECIPIENTS is empty" in result.reason


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("web_search", WebSearchInput(query="site:evil.com sk-abcdefghijklmnopqrstuvwxyz123456")),
        ("send_email", email("mentor@example.com", body="The password: hunter2")),
    ],
)
def test_secrets_never_leave_the_machine(tool: str, args) -> None:
    policy = PermissionPolicy(email_allowed_recipients=["mentor@example.com"])

    result = policy.authorize(tool, args)

    assert not result.allowed and "looks like a secret" in result.reason and not result.retryable


def test_per_run_budget() -> None:
    policy = PermissionPolicy(budgets_per_run={"web_search": 2})
    query = WebSearchInput(query="ai jobs")

    assert [policy.authorize("web_search", query, run_id="r1").allowed for _ in range(3)] == [True, True, False]
    assert policy.authorize("web_search", query, run_id="r2").allowed  # budgets are per run
    policy.forget_run("r1")
    assert policy.authorize("web_search", query, run_id="r1").allowed


def test_rate_limit_uses_a_sliding_one_minute_window() -> None:
    clock = FakeClock()
    policy = PermissionPolicy(rate_limits_per_minute={"web_search": 2}, clock=clock)
    query = WebSearchInput(query="ai jobs")

    assert policy.authorize("web_search", query).allowed
    assert policy.authorize("web_search", query).allowed
    limited = policy.authorize("web_search", query)
    assert not limited.allowed and limited.retryable and limited.reason.startswith("Rate limit")

    clock.now += 61  # the window slides: old calls no longer count
    assert policy.authorize("web_search", query).allowed


def test_denied_calls_do_not_use_up_the_budget() -> None:
    policy = PermissionPolicy(budgets_per_run={"send_email": 1}, email_allowed_recipients=["ok@example.com"])

    assert not policy.authorize("send_email", email("bad@evil.com"), run_id="r").allowed
    assert policy.authorize("send_email", email("ok@example.com"), run_id="r").allowed


# ------------------------------------------------------- registry enforcement
def mock_search_tool() -> MagicMock:
    tool = MagicMock(spec=AgentTool)
    tool.name, tool.input_model = "web_search", WebSearchInput
    tool.run = AsyncMock(return_value="results")
    return tool


async def test_registry_denies_before_the_tool_runs() -> None:
    tool = mock_search_tool()
    registry = ToolRegistry(policy=PermissionPolicy(disabled_tools=["web_search"]))
    registry.register(tool)

    result = await registry.execute("web_search", {"query": "ai jobs"})

    assert result.status == ToolStatus.DENIED and "disabled" in result.error
    assert "blocked by the permission policy" in result.to_llm_text()
    tool.run.assert_not_awaited()


async def test_registry_passes_run_id_to_budgets() -> None:
    tool = mock_search_tool()
    registry = ToolRegistry(policy=PermissionPolicy(budgets_per_run={"web_search": 1}))
    registry.register(tool)

    first = await registry.execute("web_search", {"query": "ai jobs"}, run_id="r1")
    second = await registry.execute("web_search", {"query": "ml jobs"}, run_id="r1")

    assert first.ok and second.status == ToolStatus.DENIED and "budget" in second.error


def test_disabled_tools_are_not_registered(tmp_path) -> None:
    settings = Settings(_env_file=None, documents_dir=tmp_path, disabled_tools=["python_exec", "send_email"])

    available = {t["name"]: t["available"] for t in build_default_registry(settings).describe()}

    assert available["python_exec"] is False and available["send_email"] is False
    assert available["calculator"] is True
