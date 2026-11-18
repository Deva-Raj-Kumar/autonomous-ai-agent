"""API fuzzing: whatever a client sends, the server answers 2xx/4xx, never 500.

A 500 means input reached code that didn't expect it: exactly where injection bugs,
crashes and data leaks live. Classic attack strings are pinned with @example."""

import json
from urllib.parse import quote

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from tests.support.stack import PASSWORD, sign_up

pytestmark = pytest.mark.real_auth

FUZZ = settings(max_examples=60, deadline=None,
                suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
ATTACKS = ["'; DROP TABLE users; --", "\" OR 1=1 --", "<script>alert(1)</script>", "../../../../etc/passwd",
           "{{7*7}}", "${jndi:ldap://x}", "\x00", "\ud800", "A" * 5000, "🙂" * 300, "%00%2e%2e%2f"]
HOSTILE_TEXT = st.one_of(st.sampled_from(ATTACKS), st.text(max_size=400))


@pytest.fixture
def user(client):
    return sign_up(client, "fuzz@example.com")


def assert_handled(response) -> None:
    assert response.status_code < 500, (response.status_code, response.text[:300])


# Send exactly what an attacker can put on the wire, bypassing client-side encoding:
# raw JSON text (json.dumps writes a lone surrogate as a VALID JSON escape sequence)
# and raw percent-encoded bytes (which may be invalid UTF-8).
def raw_json(user, method: str, path: str, body):
    headers = {**user.headers, "Content-Type": "application/json"}
    return user.client.request(method, path, content=json.dumps(body), headers=headers)


def encoded(text: str) -> str:
    return quote(text.encode("utf-8", "surrogatepass"), safe="")


@FUZZ
@given(content=HOSTILE_TEXT, query=HOSTILE_TEXT)
def test_memory_endpoints_never_crash(user, content: str, query: str) -> None:
    # (Not asserting the stored text: near-duplicates are deliberately merged into the
    # existing memory, e.g. '" OR 1=1 --' and '1' share their only token.)
    assert_handled(raw_json(user, "POST", "/memories", {"content": content}))
    assert_handled(user.get(f"/memories/search?q={encoded(query)}"))


@FUZZ
@given(segment=HOSTILE_TEXT.filter(lambda s: s and "/" not in s and "?" not in s and "#" not in s))
def test_path_parameters_never_crash(user, segment: str) -> None:
    for path in ("/agent/runs/{}", "/agent/runs/{}/history", "/chat/{}/history", "/memories/{}"):
        method = user.delete if path == "/memories/{}" else user.get
        assert_handled(method(path.format(encoded(segment))))


@FUZZ
@given(body=st.one_of(st.none(), st.integers(), st.text(max_size=50),
                      st.dictionaries(st.text(max_size=10), st.text(max_size=20) | st.integers(), max_size=4)))
def test_malformed_bodies_get_422_not_500(user, body) -> None:
    for path in ("/agent/runs", "/memories", "/chat", "/agent/runs/x/approval"):
        assert_handled(raw_json(user, "POST", path, body))


@example("'; DROP TABLE users; --")
@settings(max_examples=1, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.just("'; DROP TABLE memories; --"))
def test_sql_injection_is_stored_as_plain_text(user, payload: str) -> None:
    user.post("/memories", json={"content": payload})

    # The tables still exist and still work: the payload was a VALUE, never SQL.
    assert payload in [m["content"] for m in user.get("/memories").json()]
    again = user.client.post("/auth/login", data={"username": "fuzz@example.com", "password": PASSWORD})
    assert again.status_code == 200
