"""Tests for secret detection and redaction."""

import pytest

from app.safety.secrets import contains_secret, redact_secrets


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("my key is sk-abcdefghijklmnopqrstuvwxyz123456", "sk-abcdefghijklmnopqrstuvwxyz123456"),
        ("google AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("tavily tvly-abcdefghijklmnop1234", "tvly-abcdefghijklmnop1234"),
        ("gh token ghp_" + "a" * 36, "ghp_" + "a" * 36),
        ("aws AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        ("password: hunter2 ok", "hunter2"),
        ("my api key = abc123xyz", "abc123xyz"),
        ("db postgresql://admin:S3cr3t@localhost:5432/app", "S3cr3t"),
        ("card 4111 1111 1111 1111 exp 12/29", "4111 1111 1111 1111"),
    ],
)
def test_secrets_are_redacted(text: str, secret: str) -> None:
    redacted = redact_secrets(text)

    assert secret not in redacted
    assert "[REDACTED]" in redacted
    assert contains_secret(text)


@pytest.mark.parametrize(
    "text",
    [
        "I live in Hyderabad and know Python",
        "call me at 9876543210",  # phone number: 10 digits, not a card
        "order id 1234567890123",  # 13 digits but fails the Luhn check
        "my pin code is 500081",  # Indian postal PIN code
        "the token economy is interesting",  # 'token' without a value
    ],
)
def test_normal_text_is_untouched(text: str) -> None:
    assert redact_secrets(text) == text
    assert not contains_secret(text)


def test_url_keeps_user_and_host() -> None:
    assert redact_secrets("postgresql://admin:pw@db:5432/x") == "postgresql://admin:[REDACTED]@db:5432/x"
