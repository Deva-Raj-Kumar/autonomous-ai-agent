"""Logging setup. One consistent log format for the whole app.

We use the standard `logging` module instead of print(), because log lines
have levels (DEBUG/INFO/WARNING/ERROR), timestamps and the module name, and
can later be sent to files or monitoring tools (Phase 15) without code changes.

SECURITY (Phase 10): every handler gets a RedactingFilter. Logs are often shipped to
monitoring services and pasted into bug reports, so a secret that reaches a log line
has effectively leaked. The filter rewrites each record with redact_secrets() before
any handler formats it.
"""

import logging

from app.safety.secrets import redact_secrets

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
# uvicorn configures its own handlers (not on the root logger), so they get the filter too.
OTHER_LOGGERS_WITH_HANDLERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class RedactingFilter(logging.Filter):
    """Replaces API keys, passwords, URL credentials and card numbers with [REDACTED]."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()  # the message with its %-arguments filled in
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg, record.args = redacted, ()  # args already merged into the message
        if record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        return True  # never drop the record, only clean it


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger. Call once, at application startup."""
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,  # replace any handlers configured earlier (e.g. on reload)
    )
    redacting = RedactingFilter()
    for name in ("", *OTHER_LOGGERS_WITH_HANDLERS):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(redacting)
    # Third-party libraries can be noisy at INFO; keep only their warnings.
    for noisy in ("httpx", "httpcore", "chromadb", "google_genai", "alembic", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
