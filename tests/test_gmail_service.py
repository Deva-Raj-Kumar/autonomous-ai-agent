"""Unit tests for GmailService (OAuth 2.0, users.messages.send, deduplication, error handling)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.gmail_service import GmailAPIError, GmailService


def test_gmail_service_deduplication():
    service = GmailService()
    to = ["dev@example.com"]
    subject = "Meeting Today"
    body = "Hi Dev, let's meet."

    # First send succeeds
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "msg_12345", "threadId": "thread_abc"},
        )
        with patch.dict(os.environ, {"GMAIL_ACCESS_TOKEN": "test-mock-token"}):
            res1 = service.send_email(to=to, subject=subject, body=body)
            assert res1.success is True
            assert res1.message_id == "msg_12345"
            assert mock_post.call_count == 1

            # Second identical send is deduplicated (no second network call)
            res2 = service.send_email(to=to, subject=subject, body=body)
            assert res2.success is True
            assert res2.message_id == "msg_12345"
            assert "deduplicated" in res2.status
            assert mock_post.call_count == 1  # Still 1: network was NOT called again


def test_gmail_service_requires_token():
    service = GmailService()
    # Ensure no token in env
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(GmailAPIError, match="No valid OAuth 2.0 token found"):
            service.send_email(to=["a@b.com"], subject="Test", body="Hello")


def test_gmail_service_handles_auth_error_401():
    service = GmailService()
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=401,
            text="Invalid Credentials",
            json=lambda: {"error": {"message": "Invalid Credentials"}},
        )
        with patch.dict(os.environ, {"GMAIL_ACCESS_TOKEN": "expired-token"}):
            with pytest.raises(GmailAPIError, match="Gmail API authorization error"):
                service.send_email(to=["a@b.com"], subject="Test", body="Hello")


def test_gmail_service_handles_permission_error_403():
    service = GmailService()
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=403,
            text="Insufficient Permission",
            json=lambda: {"error": {"message": "Insufficient Permission"}},
        )
        with patch.dict(os.environ, {"GMAIL_ACCESS_TOKEN": "token-without-send-scope"}):
            with pytest.raises(GmailAPIError, match="gmail.send"):
                service.send_email(to=["a@b.com"], subject="Test", body="Hello")
