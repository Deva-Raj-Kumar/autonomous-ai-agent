"""Request ids, safe 500s, CORS and readiness."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import install_middleware
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_every_response_gets_a_request_id(client: TestClient) -> None:
    first, second = client.get("/health"), client.get("/health")

    assert len(first.headers["X-Request-ID"]) == 32
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_a_safe_client_request_id_is_kept_and_an_unsafe_one_replaced(client: TestClient) -> None:
    kept = client.get("/health", headers={"X-Request-ID": "frontend-abc-123"})
    replaced = client.get("/health", headers={"X-Request-ID": "x\r\nFAKE LOG LINE"})

    assert kept.headers["X-Request-ID"] == "frontend-abc-123"
    assert "FAKE" not in replaced.headers["X-Request-ID"]  # no log injection


def test_unhandled_errors_return_a_generic_500(caplog: pytest.LogCaptureFixture) -> None:
    broken = FastAPI()
    install_middleware(broken)

    @broken.get("/boom")
    async def boom() -> None:
        raise RuntimeError("SELECT * FROM users WHERE password = 'hunter2'")

    with caplog.at_level(logging.ERROR), TestClient(broken, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error."
    assert "hunter2" not in response.text and "SELECT" not in response.text  # details stay in the log
    assert response.json()["request_id"] in caplog.text  # ...where the request id finds them


def test_cors_allows_only_the_configured_frontend(client: TestClient) -> None:
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "Authorization"}

    allowed = client.options("/memories", headers={"Origin": "http://localhost:3000", **preflight})
    blocked = client.options("/memories", headers={"Origin": "https://evil.example", **preflight})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in blocked.headers


def test_readiness_reports_a_missing_database(client: TestClient) -> None:
    client.app.state.database = None

    response = client.get("/health/ready")

    assert response.status_code == 503 and response.json()["database"] is False


def test_validation_errors_never_echo_what_was_sent(client: TestClient) -> None:
    response = client.post("/auth/register", json={"email": "a@example.com", "username": "anu", "password": "password123"})

    assert response.status_code == 422
    assert "password123" not in response.text  # the default handler would reflect it
    assert response.json()["detail"][0]["msg"].endswith("Password is too easy to guess.")


def test_text_that_is_not_valid_unicode_gets_a_clean_400(client: TestClient) -> None:
    lone_surrogate = rb'{"content": "\ud800"}'  # valid JSON syntax, impossible as UTF-8
    invalid_utf8 = b'{"content": "\xff\xfe"}'

    for body in (lone_surrogate, invalid_utf8):
        response = client.post("/memories", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 400, response.text


def test_real_unicode_still_works(client: TestClient) -> None:
    # A correctly PAIRED surrogate escape (an emoji) plus Telugu text: both must pass.
    slash = chr(92)  # a backslash, built at runtime so no editor or shell can mangle it
    body = ('{"content": "Ravi likes ' + slash + 'ud83d' + slash + 'ude42 and తెలుగు"}').encode()

    response = client.post("/memories", content=body, headers={"Content-Type": "application/json"})

    assert response.status_code == 201 and response.json()["content"].startswith("Ravi likes \U0001f642")
