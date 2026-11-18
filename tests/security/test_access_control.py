"""IDOR (insecure direct object reference) and mass assignment, through the real API.

IDOR: user B takes an id that belongs to user A (from a URL, a log, a guess) and tries
every endpoint that accepts it. Every attempt must look like "not found", and A's data
must be unchanged afterwards."""

import pytest

from tests.support.stack import sign_up

pytestmark = pytest.mark.real_auth


@pytest.fixture
def victim_and_attacker(client):
    asha, mallory = sign_up(client, "asha@example.com"), sign_up(client, "mallory@example.com")
    run_id = asha.start_run("Email the average salary to my mentor")
    assert asha.wait(run_id)["status"] == "waiting_approval"
    memory_id = asha.post("/memories", json={"content": "Asha's salary expectation is 18 LPA"}).json()["id"]
    session = asha.post("/chat", json={"message": "Hi, this is private"}).json()["session_id"]
    return asha, mallory, {"run": run_id, "memory": memory_id, "session": session}


ATTACKS = [
    ("GET", "/agent/runs/{run}", None),
    ("GET", "/agent/runs/{run}/history", None),
    ("POST", "/agent/runs/{run}/approval", {"approved": ["t2"]}),
    ("POST", "/agent/runs/{run}/continue", None),
    ("PUT", "/memories/{memory}", {"content": "overwritten by mallory"}),
    ("DELETE", "/memories/{memory}", None),
    ("GET", "/chat/{session}/history", None),
    ("DELETE", "/chat/{session}", None),
]


@pytest.mark.parametrize(("method", "template", "body"), ATTACKS, ids=[f"{m} {t}" for m, t, _ in ATTACKS])
def test_someone_elses_ids_are_not_found(victim_and_attacker, method, template, body) -> None:
    asha, mallory, ids = victim_and_attacker
    url = template.format(**ids)

    response = mallory.client.request(method, url, headers=mallory.headers, json=body)

    # 404 for objects; an empty list for chat history (the session doesn't exist FOR HER).
    assert response.status_code == 404 or response.json() == [], (response.status_code, response.text)


def test_the_victims_data_is_unchanged_after_all_attacks(victim_and_attacker) -> None:
    asha, mallory, ids = victim_and_attacker
    for method, template, body in ATTACKS:
        mallory.client.request(method, template.format(**ids), headers=mallory.headers, json=body)

    assert asha.get(f"/agent/runs/{ids['run']}").json()["status"] == "waiting_approval"
    assert [m["content"] for m in asha.get("/memories").json()] == ["Asha's salary expectation is 18 LPA"]
    assert len(asha.get(f"/chat/{ids['session']}/history").json()) == 2
    assert mallory.get("/approvals").json() == [] and mallory.get("/agent/runs").json() == []


def test_posting_to_someone_elses_session_id_starts_your_own_chat(victim_and_attacker) -> None:
    asha, mallory, ids = victim_and_attacker

    mallory.post("/chat", json={"message": "injecting into your chat", "session_id": ids["session"]})

    asha_messages = [m["content"] for m in asha.get(f"/chat/{ids['session']}/history").json()]
    assert "injecting into your chat" not in asha_messages


def test_mass_assignment_cannot_grant_admin_or_change_owners(client) -> None:
    sneaky = client.post("/auth/register", json={
        "email": "sneaky@example.com", "username": "sneaky", "password": "correct horse battery staple",
        "is_admin": True, "is_active": True, "id": 1,
    })
    assert sneaky.status_code == 201 and sneaky.json()["is_admin"] is False and sneaky.json()["id"] != 1

    asha, mallory = sign_up(client, "asha@example.com"), sign_up(client, "mallory@example.com")
    created = mallory.post("/memories", json={"content": "planted fact", "user_id": asha.id}).json()

    assert asha.get("/memories").json() == []  # the extra user_id field was ignored
    assert [m["id"] for m in mallory.get("/memories").json()] == [created["id"]]
