"""User journeys across every layer. Each test reads like a story a user lives through."""

import email
from pathlib import Path

import pytest

from tests.support.scripted_llm import EMAIL_TO
from tests.support.stack import sign_up

pytestmark = pytest.mark.real_auth


def test_goal_to_report_with_permanent_history(client) -> None:
    asha = sign_up(client, "asha@example.com")

    run_id = asha.start_run("Calculate the average of 45000, 52000 and 61000 and write a report")
    view = asha.wait(run_id)

    assert view["status"] == "completed"
    assert [t["status"] for t in view["plan"]["tasks"]] == ["completed", "completed"]
    assert "= 52666.666" in view["records"][0]["output_preview"]  # the REAL calculator ran
    assert "52,666.67" in view["final_output"]
    history = asha.get(f"/agent/runs/{run_id}/history").json()
    assert [(log["tool_name"], log["status"]) for log in history["tool_logs"]] == [
        ("calculator", "success"), ("generate_report", "success"),
    ]
    assert [r["run_id"] for r in asha.get("/agent/runs").json()] == [run_id]


def test_approved_email_is_sent_exactly_as_shown(client, stack_env: Path) -> None:
    asha = sign_up(client, "asha@example.com")

    run_id = asha.start_run("Calculate the average salary and email it to my mentor")
    waiting = asha.wait(run_id)

    assert waiting["status"] == "waiting_approval"
    shown = waiting["pending_approvals"][0]
    assert shown["tool"] == "send_email" and shown["arguments"]["to"] == [EMAIL_TO]
    pending = asha.get("/approvals", params={"status": "pending"}).json()
    assert [(a["run_id"], a["task_id"]) for a in pending] == [(run_id, "t2")]

    assert asha.post(f"/agent/runs/{run_id}/approval", json={"approved": ["t2"]}).status_code == 202
    done = asha.wait(run_id)

    assert done["status"] == "completed"
    sent = list((stack_env / "outbox").glob("*.eml"))
    assert len(sent) == 1
    message = email.message_from_bytes(sent[0].read_bytes())
    assert message["To"] == EMAIL_TO and message.get_payload().strip() == shown["arguments"]["body"]
    audit = asha.get("/approvals", params={"run_id": run_id}).json()[0]
    assert audit["status"] == "approved" and audit["decided_by"] == f"user:{asha.id}:asha"


def test_rejected_email_is_never_sent(client, stack_env: Path) -> None:
    asha = sign_up(client, "asha@example.com")
    run_id = asha.start_run("Email the average salary to my mentor")
    asha.wait(run_id)

    asha.post(f"/agent/runs/{run_id}/approval", json={"approved": []})
    done = asha.wait(run_id)

    assert {t["id"]: t["status"] for t in done["plan"]["tasks"]}["t2"] == "skipped"
    assert list((stack_env / "outbox").glob("*.eml")) == []
    assert asha.get("/approvals", params={"run_id": run_id}).json()[0]["status"] == "rejected"


def test_a_paused_run_survives_a_server_restart(start_app, stack_env: Path) -> None:
    with start_app() as first_server:
        asha = sign_up(first_server, "asha@example.com")
        run_id = asha.start_run("Email the average salary to my mentor")
        assert asha.wait(run_id)["status"] == "waiting_approval"
        token = asha.headers

    with start_app() as second_server:  # a brand-new process state: only files remain
        asha_again = sign_up(second_server, "asha@example.com")
        assert asha_again.headers != token  # new login; same account, same data
        assert asha_again.get(f"/agent/runs/{run_id}").json()["status"] == "waiting_approval"
        asha_again.post(f"/agent/runs/{run_id}/approval", json={"approved": ["t2"]})
        assert asha_again.wait(run_id)["status"] == "completed"
    assert len(list((stack_env / "outbox").glob("*.eml"))) == 1


def test_chat_remembers_and_the_user_controls_memory(client) -> None:
    ravi = sign_up(client, "ravi@example.com")

    turn = ravi.post("/chat", json={"message": "Please remember that I prefer remote jobs"}).json()

    assert turn["memory_changes"][0]["applied"] is True
    memories = ravi.get("/memories").json()
    assert [m["content"] for m in memories] == ["User said: I prefer remote jobs."]
    history = ravi.get(f"/chat/{turn['session_id']}/history").json()
    assert [m["role"] for m in history] == ["user", "assistant"]

    assert ravi.delete(f"/memories/{memories[0]['id']}").status_code == 204
    assert ravi.get("/memories").json() == []


def test_two_users_work_side_by_side_without_seeing_each_other(client) -> None:
    asha, ravi = sign_up(client, "asha@example.com"), sign_up(client, "ravi@example.com")
    asha_run = asha.start_run("Email the average salary to my mentor")
    ravi_run = ravi.start_run("Calculate the average salary and write a report")
    asha.wait(asha_run)
    ravi.wait(ravi_run)

    assert [r["run_id"] for r in asha.get("/agent/runs").json()] == [asha_run]
    assert [r["run_id"] for r in ravi.get("/agent/runs").json()] == [ravi_run]
    assert ravi.get("/approvals").json() == []  # Asha's pending email is not Ravi's business
    assert ravi.post(f"/agent/runs/{asha_run}/approval", json={"approved": ["t2"]}).status_code == 404
    assert asha.get(f"/agent/runs/{asha_run}").json()["status"] == "waiting_approval"  # untouched
