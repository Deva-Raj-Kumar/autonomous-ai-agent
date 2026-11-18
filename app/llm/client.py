"""Creates the chat model object that the rest of the app talks to.

This is the ONLY file that knows which provider (Gemini / OpenAI) we use.
Everything else receives a LangChain `BaseChatModel` and calls the same methods
(.ainvoke, .with_structured_output, .bind_tools) no matter which provider is behind it.
"""

import logging
import re

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Our provider names -> LangChain's provider names for init_chat_model().
_PROVIDER_MAP = {
    "gemini": "google_genai",  # uses the langchain-google-genai package
    "openai": "openai",  # needs:  pip install langchain-openai
}


class LLMError(RuntimeError):
    """Raised when an LLM call fails (network, quota, bad output...)."""


class LLMConfigurationError(LLMError):
    """Raised when the LLM can't be created (missing API key, missing package)."""


# Status codes that mean "try again / try elsewhere", not "your request is wrong".
TEMPORARY_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_TEMPORARY_CODE_IN_TEXT = re.compile(r"(?<!\d)(408|429|500|502|503|504)(?!\d)")
_TEMPORARY_MARKERS = ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "high demand",
                      "overloaded", "rate limit", "timed out", "timeout")


def is_temporary_error(exc: BaseException) -> bool:
    """True for provider-side, temporary failures: overloaded (503), rate limited (429),
    5xx, timeouts. A different model may succeed. False for errors in OUR request (400,
    401 bad key, 404 unknown model): another model would fail the same way."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:  # follow the "raise ... from" chain
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        for attribute in ("code", "status_code"):
            value = getattr(current, attribute, None)
            if isinstance(value, int) and value in TEMPORARY_STATUS_CODES:
                return True
        text = str(current)
        if _TEMPORARY_CODE_IN_TEXT.search(text):  # e.g. "503 UNAVAILABLE. {...}"
            return True
        if any(marker.lower() in text.lower() for marker in _TEMPORARY_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def create_chat_model(
    settings: Settings | None = None,
    *,
    temperature: float | None = None,
    model_name: str | None = None,
) -> BaseChatModel:
    """Build a chat model for the provider selected in settings.

    Args:
        settings: app settings; defaults to the shared get_settings() instance.
        temperature: override the configured temperature for this one model.
        model_name: a specific model (e.g. a fallback) instead of the configured one.

    Raises:
        LLMConfigurationError: if the API key or the provider package is missing.
    """
    settings = settings or get_settings()

    if not settings.llm_api_key_configured:
        raise LLMConfigurationError(
            f"No API key configured for provider '{settings.llm_provider}'. "
            "Add it to your .env file (see .env.example)."
        )

    api_key = (
        settings.google_api_key if settings.llm_provider == "gemini" else settings.openai_api_key
    )

    try:
        # init_chat_model is LangChain's provider-agnostic factory. The keyword
        # arguments below are common to all chat models, so switching provider
        # needs no code changes.
        model = init_chat_model(
            model_name or settings.active_model,
            model_provider=_PROVIDER_MAP[settings.llm_provider],
            api_key=api_key,  # SecretStr: stays masked if the model object is printed
            temperature=settings.llm_temperature if temperature is None else temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    except ImportError as exc:  # e.g. langchain-openai not installed
        raise LLMConfigurationError(
            f"The package for provider '{settings.llm_provider}' is not installed: {exc}"
        ) from exc

    logger.debug("Created chat model %s (%s)", model_name or settings.active_model, settings.llm_provider)
    return model
