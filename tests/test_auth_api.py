"""End-to-end authentication over HTTP: REAL tokens, REAL Argon2, a fresh in-memory
database per test (each TestClient start runs the lifespan again). Nothing is mocked."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.throttle import LoginThrottle
from app.config import get_settings
from app.main import app

pytestmark = pytest.mark.real_auth
PASSWORD = "correct horse battery staple"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def signup(client: TestClient, email: str = "ravi@example.com", username: str = "ravi") -> dict:
    assert client.post("/auth/register", json={"email": email, "username": username, "password": PASSWORD}).status_code == 201
    response = client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ---------------------------------------------------------- register / login
def test_register_login_and_me(client: TestClient) -> None:
    created = client.post("/auth/register", json={"email": "Ravi@Example.com", "username": "ravi", "password": PASSWORD})

    assert created.status_code == 201
    assert created.json()["email"] == "ravi@example.com"  # normalised
    assert "password" not in created.text and "argon2" not in created.text

    tokens = client.post("/auth/login", data={"username": "RAVI@example.com", "password": PASSWORD}).json()
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == get_settings().access_token_minutes * 60

    me = client.get("/auth/me", headers=bearer(tokens)).json()
    assert (me["username"], me["is_admin"], me["last_login_at"] is not None) == ("ravi", False, True)


def test_duplicate_email_and_weak_password(client: TestClient) -> None:
    signup(client)

    again = client.post("/auth/register", json={"email": "ravi@example.com", "username": "other", "password": PASSWORD})
    weak = client.post("/auth/register", json={"email": "new@example.com", "username": "new", "password": "password123"})
    local = client.post("/auth/register", json={"email": "local@localhost", "username": "other", "password": PASSWORD})

    assert again.status_code == 409
    assert weak.status_code == 422 and "too easy" in weak.text
    assert local.status_code == 422  # not even a valid email address


def test_wrong_password_and_unknown_email_look_identical(client: TestClient) -> None:
    signup(client)

    wrong = client.post("/auth/login", data={"username": "ravi@example.com", "password": "not the password"})
    unknown = client.post("/auth/login", data={"username": "nobody@example.com", "password": "not the password"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect email or password."}


def test_registration_can_be_closed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_REGISTRATION", "false")
    get_settings.cache_clear()
    try:
        response = client.post("/auth/register", json={"email": "a@example.com", "username": "anu", "password": PASSWORD})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 403


def test_repeated_failures_are_throttled(client: TestClient) -> None:
    signup(client)
    client.app.state.login_throttle = LoginThrottle(max_failures=2, window_seconds=60)
    bad = {"username": "ravi@example.com", "password": "guess guess guess"}

    codes = [client.post("/auth/login", data=bad).status_code for _ in range(3)]
    correct_now = client.post("/auth/login", data={"username": "ravi@example.com", "password": PASSWORD})

    assert codes == [401, 401, 429]
    assert correct_now.status_code == 429 and int(correct_now.headers["Retry-After"]) > 0  # even the right password waits


# ------------------------------------------------------------ protection
@pytest.mark.parametrize(("method", "path"), [
    ("get", "/memories"), ("get", "/agent/runs"), ("get", "/approvals"), ("get", "/tools"),
    ("post", "/llm/chat"), ("get", "/knowledge/documents"), ("get", "/auth/me"),
])
def test_protected_endpoints_need_a_token(client: TestClient, method: str, path: str) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_garbage_and_refresh_tokens_are_not_access_tokens(client: TestClient) -> None:
    tokens = signup(client)

    assert client.get("/memories", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/memories", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401


def test_public_endpoints_stay_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["database"] is True


def test_deactivated_user_is_locked_out_immediately(client: TestClient) -> None:
    tokens = signup(client)
    assert client.get("/memories", headers=bearer(tokens)).status_code == 200

    client.app.state.auth_service.set_flags("ravi@example.com", is_active=False)

    assert client.get("/memories", headers=bearer(tokens)).status_code == 401  # token not expired, still refused
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/auth/login", data={"username": "ravi@example.com", "password": PASSWORD}).status_code == 401


def test_shared_knowledge_base_changes_are_admin_only(client: TestClient) -> None:
    tokens = signup(client)

    assert client.post("/knowledge/ingest", headers=bearer(tokens)).status_code == 403
    client.app.state.auth_service.set_flags("ravi@example.com", is_admin=True)
    assert client.post("/knowledge/ingest", headers=bearer(tokens)).status_code != 403


# ------------------------------------------------------ refresh / logout
def test_refresh_rotates_tokens(client: TestClient) -> None:
    first = signup(client)

    second = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    assert client.get("/auth/me", headers=bearer(second.json())).status_code == 200


def test_reusing_a_refresh_token_ends_the_whole_login(client: TestClient) -> None:
    stolen = signup(client)["refresh_token"]
    legit = client.post("/auth/refresh", json={"refresh_token": stolen}).json()  # the real user refreshes

    replay = client.post("/auth/refresh", json={"refresh_token": stolen})  # the thief replays the old one

    assert replay.status_code == 401 and "reuse detected" in replay.json()["detail"]
    # The family is revoked: the real user's NEWER token stopped working too.
    assert client.post("/auth/refresh", json={"refresh_token": legit["refresh_token"]}).status_code == 401


def test_logout_revokes_only_that_login(client: TestClient) -> None:
    laptop = signup(client)
    phone = client.post("/auth/login", data={"username": "ravi@example.com", "password": PASSWORD}).json()

    assert client.post("/auth/logout", json={"refresh_token": laptop["refresh_token"]}).status_code == 204

    assert client.post("/auth/refresh", json={"refresh_token": laptop["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": phone["refresh_token"]}).status_code == 200
    assert client.post("/auth/logout", json={"refresh_token": laptop["refresh_token"]}).status_code == 204  # idempotent


def test_tokens_from_another_server_key_are_rejected(client: TestClient) -> None:
    from app.auth.security import TokenConfig, create_access_token

    other_server = TokenConfig(secret="some-other-deployment-" + "z" * 40)

    assert client.get("/auth/me", headers={"Authorization": f"Bearer {create_access_token(1, other_server)}"}).status_code == 401


def test_timestamps_are_sent_as_utc(client: TestClient) -> None:
    tokens = signup(client)

    me = client.get("/auth/me", headers=bearer(tokens)).json()  # read back from the database
    memory = client.post("/memories", json={"content": "Ravi likes chai."}, headers=bearer(tokens)).json()

    # "Z" (or +00:00): browsers convert to local time correctly instead of guessing.
    for value in (me["created_at"], me["last_login_at"], memory["created_at"]):
        assert value.endswith(("Z", "+00:00")), value
