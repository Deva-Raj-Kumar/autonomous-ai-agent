"""Full-stack harness (integration + security tests): the REAL application, end to end, with only the LLM scripted.

Real: HTTP + auth + per-user scoping + LangGraph workflow + checkpoints (a file) +
Alembic-migrated database (a file) + tools (calculator, send_email outbox) + reports.
Fake: the LLM (tests/support/scripted_llm.py), so runs are fast, free and repeatable.
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm.service import LLMService
from app.main import app
from tests.support.scripted_llm import EMAIL_TO, scripted_llm

PASSWORD = "correct horse battery staple"


@pytest.fixture
def stack_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Settings for one isolated deployment, living in tmp_path."""
    env = {
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'agent.db').as_posix()}",
        "DB_AUTO_MIGRATE": "true",  # the real Alembic migrations build the schema
        "CHECKPOINT_DB_PATH": str(tmp_path / "checkpoints.db"),
        "EMAIL_OUTBOX_DIR": str(tmp_path / "outbox"),
        "EMAIL_ALLOWED_RECIPIENTS": json.dumps([EMAIL_TO]),
        "GOOGLE_API_KEY": "scripted-not-a-real-key",  # makes the app build the workflow
        "JWT_SECRET_KEY": "integration-test-secret-" + "x" * 40,  # tokens survive restarts
        "EVALUATION_MODE": "rules",
        "AGENT_RETRY_DELAY_SECONDS": "0",
        "MEMORY_SEMANTIC_SEARCH": "false",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def start_app(stack_env: Path):
    """start_app() -> a running TestClient. Call it again after closing to 'restart'."""
    llm = scripted_llm()
    with patch.object(LLMService, "from_settings", return_value=llm):
        yield lambda: TestClient(app)


@pytest.fixture
def client(start_app) -> Iterator[TestClient]:
    with start_app() as test_client:
        yield test_client


@dataclass
class User:
    client: TestClient
    headers: dict[str, str]
    id: int

    def get(self, path: str, **kw):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path: str, **kw):
        return self.client.post(path, headers=self.headers, **kw)

    def delete(self, path: str, **kw):
        return self.client.delete(path, headers=self.headers, **kw)

    def start_run(self, goal: str) -> str:
        response = self.post("/agent/runs", json={"goal": goal})
        assert response.status_code == 202, response.text
        return response.json()["run_id"]

    def wait(self, run_id: str, timeout: float = 20.0) -> dict:
        """Poll like the dashboard does, until the run stops working."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.get(f"/agent/runs/{run_id}")
            assert response.status_code == 200, (response.status_code, response.text)
            view = response.json()
            if not view["running"] and view["status"] not in {"planning", "executing"}:
                return view
            time.sleep(0.05)
        raise AssertionError(f"run {run_id} still working after {timeout}s: {view['status']}")


def sign_up(client: TestClient, email: str, username: str | None = None) -> User:
    username = username or email.split("@")[0]
    created = client.post("/auth/register", json={"email": email, "username": username, "password": PASSWORD})
    assert created.status_code in (201, 409), created.text
    tokens = client.post("/auth/login", data={"username": email, "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    return User(client, headers, client.get("/auth/me", headers=headers).json()["id"])
