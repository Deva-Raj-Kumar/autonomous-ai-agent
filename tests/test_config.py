"""Unit tests for app/config.py.

`_env_file=None` tells Settings NOT to read the real .env file, so tests are
isolated from your personal keys.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)  # conftest points it at in-memory SQLite
    settings = Settings(_env_file=None)

    assert settings.llm_provider == "gemini"
    assert settings.environment == "development"
    assert settings.debug is False
    assert settings.database_url.startswith("sqlite:///")
    assert settings.llm_api_key_configured is False


def test_reads_google_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-123")

    settings = Settings(_env_file=None)

    assert settings.google_api_key is not None
    assert settings.google_api_key.get_secret_value() == "test-key-123"
    assert settings.llm_api_key_configured is True


def test_accepts_gemini_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "alias-key")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key_configured is True


def test_api_key_is_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret-value")

    settings = Settings(_env_file=None)

    # SecretStr masks the value in str() and repr(), and therefore in logs.
    assert "super-secret-value" not in str(settings)
    assert "super-secret-value" not in repr(settings)


def test_empty_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.llm_api_key_configured is False


def test_openai_provider_uses_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("GOOGLE_API_KEY", "gemini-key")  # wrong provider's key

    settings = Settings(_env_file=None)

    assert settings.active_model == settings.openai_model
    assert settings.llm_api_key_configured is False


def test_invalid_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_agent_limits_are_range_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_AGENT_STEPS", "0")  # must be >= 1

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_production_refuses_to_start_without_a_jwt_secret() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="production", jwt_secret_key="too-short")

    assert Settings(_env_file=None, environment="production", jwt_secret_key="k" * 40).jwt_secret_key is not None
