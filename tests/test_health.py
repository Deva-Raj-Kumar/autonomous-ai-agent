"""API tests for the system endpoints.

TestClient sends real HTTP requests to the app in memory, so no server needs to be running.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

FAKE_KEY = "fake-key-for-tests"


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Replace the real settings with predictable fake ones for every request.
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, google_api_key=FAKE_KEY, environment="test"
    )
    with TestClient(app) as test_client:  # `with` also runs the startup/shutdown lifespan
        yield test_client
    app.dependency_overrides.clear()  # don't leak the override into other tests


def test_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["llm_provider"] == "gemini"
    assert body["llm_api_key_configured"] is True


def test_health_never_exposes_api_key(client: TestClient) -> None:
    response = client.get("/health")

    assert FAKE_KEY not in response.text


def test_openapi_docs_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
