"""Browser sessions: refresh token in an httpOnly cookie, access token in the body.
Real tokens and a real cookie jar (TestClient keeps cookies like a browser)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.real_auth
PASSWORD = "correct horse battery staple"
LOGIN = {"username": "ravi@example.com", "password": PASSWORD}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        test_client.post("/auth/register", json={"email": "ravi@example.com", "username": "ravi", "password": PASSWORD})
        yield test_client


def test_login_puts_the_refresh_token_only_in_a_protected_cookie(client: TestClient) -> None:
    response = client.post("/auth/session", data=LOGIN)

    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}  # NO refresh token for JS
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("refresh_token=", "httponly", "samesite=strict", "path=/auth/session"):
        assert attribute in cookie
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}).status_code == 200


def test_refresh_uses_and_rotates_the_cookie(client: TestClient) -> None:
    client.post("/auth/session", data=LOGIN)
    first_cookie = client.cookies.get("refresh_token")

    refreshed = client.post("/auth/session/refresh")  # no body: the browser sends the cookie

    assert refreshed.status_code == 200 and "access_token" in refreshed.json()
    assert client.cookies.get("refresh_token") not in (None, first_cookie)  # rotated


def test_replaying_an_old_cookie_ends_the_session(client: TestClient) -> None:
    client.post("/auth/session", data=LOGIN)
    stolen = client.cookies.get("refresh_token")
    client.post("/auth/session/refresh")  # the real browser rotates

    client.cookies.clear()  # the thief has only the OLD cookie
    client.cookies.set("refresh_token", stolen, path="/auth/session")
    replay = client.post("/auth/session/refresh")

    assert replay.status_code == 401 and "reuse detected" in replay.json()["detail"]
    assert 'refresh_token=""' in replay.headers["set-cookie"] or "max-age=0" in replay.headers["set-cookie"].lower()


def test_no_cookie_means_not_logged_in(client: TestClient) -> None:
    response = client.post("/auth/session/refresh")

    assert response.status_code == 401 and response.json()["detail"] == "Not logged in."


def test_logout_revokes_and_deletes_the_cookie(client: TestClient) -> None:
    client.post("/auth/session", data=LOGIN)
    old = client.cookies.get("refresh_token")

    assert client.delete("/auth/session").status_code == 204
    assert client.cookies.get("refresh_token") is None

    client.cookies.set("refresh_token", old, path="/auth/session")
    assert client.post("/auth/session/refresh").status_code == 401  # revoked server-side too


def test_wrong_password_is_throttled_like_the_api_login(client: TestClient) -> None:
    from app.auth.throttle import LoginThrottle

    client.app.state.login_throttle = LoginThrottle(max_failures=1, window_seconds=60)
    bad = {"username": "ravi@example.com", "password": "not it at all"}

    assert [client.post("/auth/session", data=bad).status_code for _ in range(2)] == [401, 429]
