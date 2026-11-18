"""Detect and redact secrets (API keys, passwords, card numbers) in text.

Why: if a user pastes an API key into the chat, we must not
  1. send it to the LLM provider (it leaves your machine),
  2. store it in the conversation history or long-term memory (it stays forever).
So user text is redacted BEFORE it goes anywhere.

Regex patterns catch common formats. They can't catch every secret, so this is one
layer of protection, not a guarantee.
"""

import re

REDACTED = "[REDACTED]"

# Each pattern matches a whole secret token.
_TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),  # OpenAI / Anthropic style keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{35,}"),  # Google API keys
    re.compile(r"\btvly-[A-Za-z0-9_-]{16,}"),  # Tavily
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key ids
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
# "password: hunter2", "api_key=abc123", "token = xyz": keep the label, hide the value.
# ("pin" is deliberately NOT included: in India "PIN code" usually means a postal code.)
_LABELLED_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|passcode|secret|api[_ -]?key|access[_ -]?token|token)"
    r"(\s*(?:is|:|=)\s*)(\S+)"
)
# Credentials inside URLs: scheme://user:PASSWORD@host
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@/]+)(@)", re.IGNORECASE)
# 13-19 digits, optionally separated by spaces or dashes (checked with Luhn below).
_CARD_CANDIDATE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_valid(number: str) -> bool:
    """The Luhn checksum all payment cards use. Filters out random long numbers."""
    digits = [int(d) for d in number if d.isdigit()]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_secrets(text: str) -> str:
    """Return `text` with every detected secret replaced by [REDACTED]."""
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(rf"\1{REDACTED}\3", text)
    text = _LABELLED_SECRET.sub(rf"\1\2{REDACTED}", text)
    return _CARD_CANDIDATE.sub(
        lambda m: REDACTED if _luhn_valid(m.group()) else m.group(), text
    )


def contains_secret(text: str) -> bool:
    return redact_secrets(text) != text
