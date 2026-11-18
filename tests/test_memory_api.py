"""API tests for /chat and /memories (GET, POST, PUT, DELETE).

The LLM is a create_autospec mock; the database is a real in-memory SQLite, so the
endpoints, SQL and validation are all exercised for real.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.routes import get_database, get_llm_service
from app.config import Settings, get_settings
from app.database.connection import Database
from app.main import app
from app.memory.schemas import MemoryExtraction


@pytest.fixture
def client(mock_llm) -> Iterator[TestClient]:
    database = Database("sqlite://")
    database.create_tables()
    mock_llm.structured.return_value = MemoryExtraction()  # extract nothing by default
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, google_api_key="k")
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_memory_crud(client: TestClient) -> None:
    created = client.post("/memories", json={"content": "User prefers remote jobs.", "category": "preference"})
    assert created.status_code == 201
    memory_id = created.json()["id"]

    assert [m["content"] for m in client.get("/memories").json()] == ["User prefers remote jobs."]

    updated = client.put(f"/memories/{memory_id}", json={"content": "User prefers hybrid jobs."})
    assert updated.json()["content"] == "User prefers hybrid jobs."

    assert client.delete(f"/memories/{memory_id}").status_code == 204
    assert client.get("/memories").json() == []
    assert client.delete(f"/memories/{memory_id}").status_code == 404


def test_create_memory_rejects_secrets(client: TestClient) -> None:
    response = client.post("/memories", json={"content": "User's password: hunter2"})

    assert response.status_code == 422
    assert "secret" in response.json()["detail"]


def test_search_shows_scores(client: TestClient) -> None:
    client.post("/memories", json={"content": "User knows Python.", "importance": 4})

    results = client.get("/memories/search", params={"q": "python"}).json()

    assert results[0]["memory"]["content"] == "User knows Python."
    assert results[0]["relevance"] == 1.0


def test_chat_session_flow(client: TestClient, mock_llm) -> None:
    mock_llm.generate.side_effect = ["Hello!", "You said hi."]  # one reply per call

    first = client.post("/chat", json={"message": "hi"}).json()
    session_id = first["session_id"]
    client.post("/chat", json={"message": "what did I say?", "session_id": session_id})

    history = client.get(f"/chat/{session_id}/history").json()
    assert [m["content"] for m in history] == ["hi", "Hello!", "what did I say?", "You said hi."]
    # The 2nd generate() call received the 1st turn as conversation history.
    second_prompt = mock_llm.generate.await_args_list[1].args[0]
    assert AIMessage("Hello!") in second_prompt

    assert client.delete(f"/chat/{session_id}").status_code == 204
    assert client.get(f"/chat/{session_id}/history").json() == []


def test_invalid_session_id_is_422(client: TestClient, mock_llm) -> None:
    response = client.post("/chat", json={"message": "hi", "session_id": "bad id!"})

    assert response.status_code == 422
    mock_llm.generate.assert_not_awaited()


def test_memory_endpoints_need_a_database() -> None:
    with TestClient(app) as client:
        client.app.state.database = None  # simulate a broken DATABASE_URL
        response = client.get("/memories")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]
