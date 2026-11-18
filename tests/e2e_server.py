"""Backend for the Playwright end-to-end tests (started by frontend/playwright.config.mjs).

    python -m tests.e2e_server --port 8020

The REAL application on a fresh temporary database, with the scripted LLM from
tests/support/scripted_llm.py: browser tests are fast, free and repeatable, and they
never touch your real database, documents or Gemini quota.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args()

    data = Path(tempfile.mkdtemp(prefix="agent_e2e_"))
    # Set BEFORE the app is imported: settings are read (and cached) at import time.
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{(data / 'agent.db').as_posix()}",
        "DB_AUTO_MIGRATE": "true",
        "CHECKPOINT_DB_PATH": str(data / "checkpoints.db"),
        "CHROMA_DIR": str(data / "chroma"),
        "DOCUMENTS_DIR": str(data / "documents"),
        "EMAIL_OUTBOX_DIR": str(data / "outbox"),
        "EMAIL_ALLOWED_RECIPIENTS": json.dumps(["mentor@example.com"]),
        "GOOGLE_API_KEY": "scripted-not-a-real-key",
        "JWT_SECRET_KEY": "e2e-only-secret-" + "x" * 48,
        "EVALUATION_MODE": "rules",
        "AGENT_RETRY_DELAY_SECONDS": "0",
        "MEMORY_SEMANTIC_SEARCH": "false",
        "LOG_LEVEL": "WARNING",
    })

    from unittest.mock import patch

    import uvicorn

    from app.llm.service import LLMService
    from tests.support.scripted_llm import scripted_llm

    try:
        with patch.object(LLMService, "from_settings", return_value=scripted_llm()):
            uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
