"""Multi-user isolation: two real accounts must never see or change each other's data.

The worst bug a multi-user app can have is a data leak between accounts, so this is
tested at BOTH levels: the stores (acting_as) and the HTTP API (real tokens)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.context import acting_as
from app.database.connection import Database, NotAuthenticatedError
from app.database.crud import RunRepository
from app.database.models import User
from app.main import app
from app.memory.long_term import LongTermMemory
from app.memory.short_term import ConversationStore
from app.safety.approval import ApprovalStore
from app.tools.database_tool import DatabaseQueryTool, QueryInput, SaveInput, SaveToDatabaseTool

PASSWORD = "correct horse battery staple"


# ---------------------------------------------------------------- store level
@pytest.fixture
def database() -> Database:
    db = Database("sqlite://")
    db.create_tables()
    with db.session() as s:
        s.add_all([User(username="asha", email="asha@example.com", password_hash="x"),
                   User(username="ravi", email="ravi@example.com", password_hash="x")])
    return db


def ids(database: Database) -> tuple[int, int]:
    with database.session() as s:
        return tuple(s.scalars(select(User.id).where(User.email != "local@localhost").order_by(User.id)))


@pytest.mark.anyio
async def test_memories_runs_and_approvals_are_per_user(database: Database) -> None:
    asha, ravi = ids(database)
    memory, runs, approvals = LongTermMemory(database), RunRepository(database), ApprovalStore(database)
    with acting_as(asha):
        note, _ = await memory.add("Asha is preparing for a data science interview.")
        await runs.create_run("asha-run", "Asha's goal")
        await approvals.request("asha-run", "t1", "send_email", "Email", {"to": ["x@example.com"]})

    with acting_as(ravi):
        assert await memory.list_memories() == []
        assert await memory.search("data science interview") == []
        assert await memory.get(note.id) is None
        assert await memory.update(note.id, "hijacked") is None
        assert await memory.delete(note.id) is False
        assert await runs.list_runs() == [] and await runs.history("asha-run") is None
        assert await runs.is_mine("asha-run") is False
        assert await approvals.list_records() == []
        assert await approvals.decide("asha-run", {"t1"}, "ravi") == []  # can't approve Asha's action

    with acting_as(asha):  # Asha's data is untouched
        assert [m.content for m in await memory.list_memories()] == [note.content]
        assert await runs.is_mine("asha-run") is True
        assert (await approvals.list_records())[0].status == "pending"


@pytest.mark.anyio
async def test_two_users_can_use_the_same_session_id(database: Database) -> None:
    asha, ravi = ids(database)
    chats = ConversationStore(database)
    with acting_as(asha):
        await chats.add_message("default", "user", "Asha's private question")
    with acting_as(ravi):
        await chats.add_message("default", "user", "Ravi's question")
        ravi_view = [m.content for m in await chats.history("default")]
        assert await chats.delete_session("default") is True  # deletes only HIS session
    with acting_as(asha):
        asha_view = [m.content for m in await chats.history("default")]

    assert ravi_view == ["Ravi's question"]
    assert asha_view == ["Asha's private question"]


@pytest.mark.anyio
async def test_database_tool_records_are_per_user(database: Database) -> None:
    asha, ravi = ids(database)
    with acting_as(asha):
        await SaveToDatabaseTool(database).run(SaveInput(kind="note", title="Salary", content="Asha's offer: 12 LPA"))
        assert "12 LPA" in await DatabaseQueryTool(database).run(QueryInput(kind="note"))
    with acting_as(ravi):
        found = await DatabaseQueryTool(database).run(QueryInput(kind="note"))

    assert "12 LPA" not in found


def test_without_a_user_the_api_side_fails_closed(database: Database) -> None:
    database.require_login = True  # what the API's lifespan sets

    with pytest.raises(NotAuthenticatedError):
        database.current_user_id()  # never a silent fallback to some default user


# ------------------------------------------------------------------ API level
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str) -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "username": email.split("@")[0], "password": PASSWORD})
    token = client.post("/auth/login", data={"username": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.real_auth
def test_api_users_cannot_see_each_others_data(client: TestClient) -> None:
    asha, ravi = login(client, "asha@example.com"), login(client, "ravi@example.com")
    created = client.post("/memories", json={"content": "Asha wants a remote ML job."}, headers=asha).json()
    asha_id = client.get("/auth/me", headers=asha).json()["id"]
    with acting_as(asha_id):  # a finished run of Asha's, in the run index
        import anyio

        anyio.run(RunRepository(client.app.state.database).create_run, "asha-run", "Asha's goal")

    assert client.get("/memories", headers=ravi).json() == []
    assert client.put(f"/memories/{created['id']}", json={"content": "x is y"}, headers=ravi).status_code == 404
    assert client.delete(f"/memories/{created['id']}", headers=ravi).status_code == 404
    assert client.get("/agent/runs/asha-run/history", headers=ravi).status_code == 404
    assert client.get("/agent/runs/asha-run/history", headers=asha).status_code == 200
    assert [m["content"] for m in client.get("/memories", headers=asha).json()] == ["Asha wants a remote ML job."]
