"""Every route the app registers is checked, not a hand-written list. Adding a new
endpoint without protection makes these tests fail, even if nobody writes a test for it.

The inventory comes from the OpenAPI schema (public, stable API). FastAPI 0.162 keeps
included routers as internal lazy objects, so walking app.routes would find nothing:
a test that silently checks zero routes is worse than no test, hence the size check."""

import re

import pytest

from app.main import app
from tests.support.stack import sign_up

pytestmark = pytest.mark.real_auth

# Deliberately public. Anything else MUST require a login.
PUBLIC = {
    ("GET", "/"), ("GET", "/health"), ("GET", "/health/ready"),
    ("POST", "/auth/register"), ("POST", "/auth/login"), ("POST", "/auth/refresh"), ("POST", "/auth/logout"),
    ("POST", "/auth/session"), ("POST", "/auth/session/refresh"), ("DELETE", "/auth/session"),
    ("POST", "/auth/google"), ("POST", "/auth/reset-password"),
}
# Change SHARED state, so they need an admin (not just any user).
ADMIN_ONLY = {("POST", "/knowledge/ingest"), ("POST", "/knowledge/upload"), ("DELETE", "/knowledge/documents/{source}")}


def all_routes() -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    )


def concrete(path: str) -> str:
    """/agent/runs/{run_id} -> /agent/runs/x1 (any value: auth is checked first)."""
    return re.sub(r"\{[^}]+\}", "x1", path)


PROTECTED = [r for r in all_routes() if r not in PUBLIC]


def test_the_inventory_is_complete() -> None:
    # If this fails, a route was added or removed: classify it in PUBLIC / ADMIN_ONLY
    # consciously, so "public" is always a decision and never an accident.
    assert len(PROTECTED) >= 25
    assert PUBLIC <= set(all_routes())
    assert ADMIN_ONLY <= set(PROTECTED)


def test_no_route_hides_from_the_inventory() -> None:
    # include_in_schema=False would hide a route from OpenAPI, and so from these tests.
    import inspect

    from app.api import auth, routes

    for module in (routes, auth):
        assert "include_in_schema=False" not in inspect.getsource(module)


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
def test_every_protected_route_rejects_anonymous_and_forged_requests(client, method: str, path: str) -> None:
    url = concrete(path)

    anonymous = client.request(method, url)
    forged = client.request(method, url, headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0."})

    assert anonymous.status_code == 401, anonymous.text
    assert forged.status_code == 401, forged.text


@pytest.mark.parametrize(("method", "path"), sorted(ADMIN_ONLY))
def test_admin_routes_refuse_normal_users(client, method: str, path: str) -> None:
    user = sign_up(client, "ravi@example.com")

    response = client.request(method, concrete(path), headers=user.headers)

    assert response.status_code == 403


def test_no_response_ever_contains_a_password_hash(client) -> None:
    user = sign_up(client, "ravi@example.com")
    bodies = [client.post("/auth/register", json={"email": "z@example.com", "username": "zed",
                                                   "password": "correct horse battery staple"}).text]
    bodies += [user.get(p).text for p in ("/auth/me", "/memories", "/agent/runs", "/approvals")]

    assert not any("argon2" in body or "password_hash" in body for body in bodies)
