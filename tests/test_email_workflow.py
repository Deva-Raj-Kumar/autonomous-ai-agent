"""Comprehensive test suite for Gmail API integration, EmailAgent,
idempotency, approval gating, outbox mode, and REST endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.agents.email_agent import EmailAgent
from app.config import Settings
from app.database.connection import Database
from app.database.email_models import EmailRecord, EmailStatus
from app.main import app
from app.services.gmail_service import GmailAPIError, GmailSendResult, GmailService


@pytest.fixture
def email_db(tmp_path: Path) -> Database:
    db = Database("sqlite:///:memory:")
    db.create_tables()
    return db


@pytest.fixture
def mock_gmail_service() -> MagicMock:
    svc = MagicMock(spec=GmailService)
    svc.resolve_access_token.return_value = "mock_token_12345"
    svc.send_email.return_value = GmailSendResult(
        message_id="msg_gmail_98765",
        thread_id="th_54321",
        detail="Email successfully dispatched via Gmail API! Message ID: msg_gmail_98765, Thread ID: th_54321.",
    )
    return svc


# 1. Draft generation
@pytest.mark.anyio
async def test_01_draft_generation(email_db: Database, tmp_path: Path) -> None:
    settings = Settings(email_mode="gmail", email_outbox_dir=tmp_path / "outbox")
    agent = EmailAgent(database=email_db, settings=settings)

    record = await agent.draft_email(
        user_id=1,
        to=["devarajkumar155@gmail.com"],
        subject="Let's Meet Today Evening",
        body="Hi Dev, are you free today evening?",
    )

    assert record.email_id.startswith("eml_")
    assert record.status == EmailStatus.PENDING_APPROVAL.value
    assert "devarajkumar155@gmail.com" in record.recipient
    assert record.subject == "Let's Meet Today Evening"


# 2. Outbox mode
@pytest.mark.anyio
async def test_02_outbox_mode(email_db: Database, tmp_path: Path) -> None:
    outbox_dir = tmp_path / "outbox"
    settings = Settings(email_mode="outbox", email_outbox_dir=outbox_dir)
    agent = EmailAgent(database=email_db, settings=settings)

    record = await agent.draft_email(
        user_id=1,
        to=["colleague@example.com"],
        subject="Project Update",
        body="Here is the status report.",
    )
    agent.approve_email(record.email_id, user_id=1)

    sent = await agent.send_email(record.email_id, user_id=1)
    assert sent.status == EmailStatus.SENT.value
    assert sent.gmail_message_id is not None
    assert sent.gmail_message_id.startswith("outbox-")
    assert len(list(outbox_dir.glob("*.eml"))) == 1


# 3. Gmail mode
@pytest.mark.anyio
async def test_03_gmail_mode(email_db: Database, mock_gmail_service: MagicMock) -> None:
    settings = Settings(email_mode="gmail", gmail_access_token=SecretStr("mock_token"))
    agent = EmailAgent(database=email_db, settings=settings, gmail_service=mock_gmail_service)

    record = await agent.draft_email(
        user_id=1,
        to=["devarajkumar155@gmail.com"],
        subject="AI Vacancy Inquiry",
        body="Inquiring about AI Engineer vacancy.",
    )
    agent.approve_email(record.email_id, user_id=1)

    sent = await agent.send_email(record.email_id, user_id=1)
    assert sent.status == EmailStatus.SENT.value
    assert sent.gmail_message_id == "msg_gmail_98765"
    assert sent.thread_id == "th_54321"
    assert mock_gmail_service.send_email.called


# 4. Missing OAuth credentials in Gmail mode
@pytest.mark.anyio
async def test_04_missing_oauth_credentials(email_db: Database) -> None:
    settings = Settings(email_mode="gmail", gmail_access_token=None, gmail_refresh_token=None)
    empty_gmail = MagicMock(spec=GmailService)
    empty_gmail.resolve_access_token.return_value = None

    agent = EmailAgent(database=email_db, settings=settings, gmail_service=empty_gmail)

    record = await agent.draft_email(
        user_id=1,
        to=["hr@techcorp.in"],
        subject="Hello",
        body="Test",
    )
    agent.approve_email(record.email_id, user_id=1)

    with pytest.raises(RuntimeError, match="Gmail API configuration missing"):
        await agent.send_email(record.email_id, user_id=1)

    latest = agent.get_record(record.email_id, user_id=1)
    assert latest is not None
    assert latest.status == EmailStatus.FAILED.value


# 5. Approval validation (prevent sending unapproved drafts)
@pytest.mark.anyio
async def test_05_approval_validation_blocks_unapproved(email_db: Database, mock_gmail_service: MagicMock) -> None:
    settings = Settings(email_mode="gmail")
    agent = EmailAgent(database=email_db, settings=settings, gmail_service=mock_gmail_service)

    record = await agent.draft_email(
        user_id=1,
        to=["devarajkumar155@gmail.com"],
        subject="Important Notice",
        body="Unapproved message",
    )
    assert record.status == EmailStatus.PENDING_APPROVAL.value

    # Attempt sending directly without calling approve_email
    with pytest.raises(ValueError, match="Approval is strictly required"):
        await agent.send_email(record.email_id, user_id=1)

    assert not mock_gmail_service.send_email.called


# 6. Successful Gmail API response (mocked HTTP 200 + ID)
def test_06_gmail_service_send_success() -> None:
    service = GmailService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "18f4a1c0d", "threadId": "18f4a1c0d_th"}

    with patch.object(service, "resolve_access_token", return_value="valid_access_token"):
        with patch("requests.post", return_value=mock_resp):
            res = service.send_email(
                to=["user@example.com"],
                subject="Test Subject",
                body="Hello World",
            )
            assert res.message_id == "18f4a1c0d"
            assert res.thread_id == "18f4a1c0d_th"
            assert "18f4a1c0d" in res.detail


# 7. Failed Gmail API response (mocked 403 / 500)
def test_07_gmail_service_handles_api_errors() -> None:
    service = GmailService()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {"error": {"message": "Insufficient Permission", "code": 403}}
    mock_resp.text = json.dumps({"error": {"message": "Insufficient Permission", "code": 403}})

    with patch.object(service, "resolve_access_token", return_value="valid_access_token"):
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(GmailAPIError, match="authorization error"):
                service.send_email(
                    to=["user@example.com"],
                    subject="Test Subject",
                    body="Hello World",
                )


# 8. Duplicate-send protection / idempotency
@pytest.mark.anyio
async def test_08_duplicate_send_idempotency(email_db: Database, mock_gmail_service: MagicMock) -> None:
    settings = Settings(email_mode="gmail")
    agent = EmailAgent(database=email_db, settings=settings, gmail_service=mock_gmail_service)

    record = await agent.draft_email(
        user_id=1,
        to=["devarajkumar155@gmail.com"],
        subject="Meeting",
        body="Let's meet today.",
    )
    agent.approve_email(record.email_id, user_id=1)

    first_res = await agent.send_email(record.email_id, user_id=1, operation_id="op_unique_1")
    assert first_res.status == EmailStatus.SENT.value
    assert mock_gmail_service.send_email.call_count == 1

    # Second send call with same email_id
    second_res = await agent.send_email(record.email_id, user_id=1, operation_id="op_unique_1")
    assert second_res.status == EmailStatus.SENT.value
    # send_email must NOT be called a second time
    assert mock_gmail_service.send_email.call_count == 1


# 9. Token refresh
def test_09_token_refresh_flow() -> None:
    settings = Settings(
        google_client_id="client_id_test",
        google_client_secret=SecretStr("client_secret_test"),
        gmail_refresh_token=SecretStr("valid_refresh_token"),
    )
    service = GmailService(settings=settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "newly_refreshed_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    with patch("requests.post", return_value=mock_resp):
        token = service._refresh_access_token()
        assert token == "newly_refreshed_access_token"
        assert service._access_token == "newly_refreshed_access_token"


# 10. Uncertain sending state after timeout
@pytest.mark.anyio
async def test_10_uncertain_status_on_timeout(email_db: Database) -> None:
    settings = Settings(email_mode="gmail")
    timeout_gmail = MagicMock(spec=GmailService)
    timeout_gmail.resolve_access_token.return_value = "token_abc"
    timeout_gmail.send_email.side_effect = TimeoutError("Connection to Gmail timed out")

    agent = EmailAgent(database=email_db, settings=settings, gmail_service=timeout_gmail)

    record = await agent.draft_email(
        user_id=1,
        to=["devarajkumar155@gmail.com"],
        subject="Urgent Update",
        body="Update details...",
    )
    agent.approve_email(record.email_id, user_id=1)

    uncertain_rec = await agent.send_email(record.email_id, user_id=1)
    assert uncertain_rec.status == EmailStatus.UNCERTAIN.value
    assert "Network timeout" in (uncertain_rec.error_message or "")


# 11. REST API Endpoints Integration Test
def test_11_rest_api_lifecycle(tmp_path: Path) -> None:
    with TestClient(app) as client:
        # Create draft
        draft_resp = client.post(
            "/api/email/draft",
            json={
                "to": ["devarajkumar155@gmail.com"],
                "subject": "REST API Test",
                "body": "Checking REST endpoint flow.",
            },
        )
        assert draft_resp.status_code == 201
        data = draft_resp.json()
        email_id = data["email_id"]
        assert data["status"] == "pending_approval"

        # Approve draft
        approve_resp = client.post(f"/api/email/{email_id}/approve")
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Fetch detail
        detail_resp = client.get(f"/api/email/{email_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["email_id"] == email_id

        # Fetch history
        history_resp = client.get("/api/email/history")
        assert history_resp.status_code == 200
        assert len(history_resp.json()) >= 1
