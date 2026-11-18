"""
Central configuration for the whole application.

Every setting lives here, in ONE typed class. Other modules never read
os.environ directly; they call get_settings(). That gives us:
  - validation at startup (a typo like LLM_PROVIDER=gemni fails immediately),
  - type conversion ("false" in .env becomes the Python bool False),
  - secrets wrapped in SecretStr so they never get printed or logged by accident.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root folder (the one containing app/, tests/, .env).
# __file__ = .../app/config.py -> parent = app/ -> parent.parent = project root.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and the .env file.

    Priority (highest first): real OS environment variables > .env file > defaults below.
    Field names are matched case-insensitively: `log_level` reads LOG_LEVEL.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",  # absolute path, so it works from any working directory
        env_file_encoding="utf-8",
        extra="ignore",  # unknown keys in .env are ignored instead of crashing
        env_ignore_empty=True,  # `OPENAI_API_KEY=` (empty) is treated as "not set"
        validate_by_name=True,  # allow Settings(google_api_key=...) in tests
        validate_by_alias=True,  # ...and also the env-var aliases defined below
    )

    # ---------- General ----------
    app_name: str = "Autonomous AI Agent"
    # Literal = only these exact values are valid; anything else raises a ValidationError.
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug_flag(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on", "debug")
        return bool(value)

    # ---------- LLM provider ----------
    # Switch providers by changing ONE line in .env.
    # Model names get retired often (gemini-2.5-flash now returns 404). Check what
    # your key can use with:  python -m app.cli models
    llm_provider: Literal["gemini", "openai"] = "gemini"
    # Fast + cheap default for development. For stronger planning use gemini-3.5-flash.
    gemini_model: str = "gemini-3.1-flash-lite"
    openai_model: str = "gpt-4.1-mini"  # not verified: check your OpenAI model list before use
    # Tried IN ORDER when the main model is temporarily unavailable (503 "high demand",
    # 429 rate limit, 5xx, timeout). JSON list in .env, e.g. GEMINI_FALLBACK_MODELS=[] to disable.
    gemini_fallback_models: list[str] = Field(
        default_factory=lambda: ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]
    )
    openai_fallback_models: list[str] = Field(default_factory=list)

    # 0 = most deterministic. Agents want repeatable plans, so keep it low.
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # Seconds to wait for one LLM response before giving up.
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # Automatic retries on temporary errors (rate limits, 5xx). Library default is 6: too many.
    llm_max_retries: int = Field(default=2, ge=0, le=10)

    # SecretStr hides the value: print(settings.google_api_key) shows '**********'.
    # Use .get_secret_value() only at the exact place the key is sent to the API.
    google_api_key: SecretStr | None = Field(
        default=None,
        # Accept either name, since Google's docs use both.
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    openai_api_key: SecretStr | None = None

    # ---------- Database ----------
    # SQLite file by default; set DATABASE_URL to MySQL/PostgreSQL in .env (Phase 11).
    database_url: str = f"sqlite:///{(DATA_DIR / 'agent.db').as_posix()}"

    # Run pending Alembic migrations at startup. Off by default: in real deployments,
    # migrations are a deliberate step (`alembic upgrade head`), not a side effect.
    db_auto_migrate: bool = False

    # ---------- Planner (Phase 3) ----------
    # A plan bigger than this is rejected: huge plans are slow, costly and usually wrong.
    max_plan_tasks: int = Field(default=12, ge=1, le=50)
    # 1 first try + repairs. Each repair sends the validation errors back to the LLM.
    planner_max_attempts: int = Field(default=3, ge=1, le=5)

    # ---------- Tools (Phase 4) ----------
    # auto = Tavily if TAVILY_API_KEY is set, otherwise DuckDuckGo (no key needed).
    search_provider: Literal["auto", "tavily", "duckduckgo"] = "auto"
    tavily_api_key: SecretStr | None = None
    search_max_results: int = Field(default=5, ge=1, le=10)
    # The ONLY folder the file reader may open. Relative paths are inside the project.
    documents_dir: Path = DATA_DIR / "documents"
    max_file_size_mb: float = Field(default=10.0, gt=0, le=100)
    # Any tool output longer than this is cut, so one result can't flood the LLM context.
    tool_max_output_chars: int = Field(default=8_000, ge=500, le=100_000)
    python_exec_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    @field_validator("documents_dir", "chroma_dir", "checkpoint_db_path", "email_outbox_dir")
    @classmethod
    def _make_dirs_absolute(cls, value: Path) -> Path:
        """DOCUMENTS_DIR=data/docs in .env means <project>/data/docs, not <current folder>/data/docs."""
        return value if value.is_absolute() else BASE_DIR / value

    # ---------- Memory (Phase 5) ----------
    # Number of most recent chat messages sent to the LLM word-for-word.
    memory_recent_messages: int = Field(default=10, ge=2, le=100)
    # When unsummarized messages exceed this, the oldest are folded into a running summary.
    memory_summarize_after: int = Field(default=20, ge=4, le=200)
    # Maximum long-term memories put into one prompt.
    memory_max_results: int = Field(default=5, ge=1, le=20)
    # Let the LLM extract lasting facts from user messages (one extra LLM call per turn).
    memory_extraction_enabled: bool = True
    # Also match memories by MEANING (embeddings), not only shared words (Phase 6).
    memory_semantic_search: bool = True

    # ---------- RAG (Phase 6) ----------
    # local  = all-MiniLM-L6-v2 via ONNX: free, private, offline after a one-time ~80 MB download.
    # gemini = Google's embedding API: uses your key and quota.
    embedding_provider: Literal["local", "gemini"] = "local"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = Field(default=768, ge=128, le=3072)
    chroma_dir: Path = DATA_DIR / "chroma"  # where ChromaDB stores vectors on disk
    # Chunk size in characters. Too small loses context; too big dilutes the match.
    rag_chunk_size: int = Field(default=800, ge=100, le=4_000)
    # Overlap keeps a sentence that crosses a chunk border findable from both sides.
    rag_chunk_overlap: int = Field(default=150, ge=0, le=1_000)
    rag_top_k: int = Field(default=4, ge=1, le=20)  # chunks given to the LLM
    rag_candidates: int = Field(default=20, ge=1, le=100)  # chunks fetched before reranking
    # hybrid = meaning + keyword overlap (free); llm = the LLM scores candidates (1 extra call).
    rag_reranker: Literal["hybrid", "llm", "none"] = "hybrid"

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE.")
        return self

    # ---------- Agent safety limits (used from Phase 7 onwards) ----------
    # ge/le = "greater/less than or equal": the values are range-checked.
    # A "step" = one tool attempt (including retries). Hard cap per run.
    max_agent_steps: int = Field(default=30, ge=1, le=100)
    max_task_retries: int = Field(default=2, ge=0, le=10)
    tool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    # Whole-run time limit: a stuck run is stopped instead of hanging forever.
    agent_run_timeout_seconds: float = Field(default=300.0, gt=0, le=3_600)
    # First retry waits this long, then 2x, 4x... (exponential backoff).
    agent_retry_delay_seconds: float = Field(default=1.0, ge=0, le=30)
    # Tasks of one wave run in parallel, but at most this many at once (rate limits!).
    agent_max_parallel_tasks: int = Field(default=4, ge=1, le=16)

    # ---------- LangGraph workflow (Phase 8) ----------
    # Checkpoints (saved workflow state) live in their own SQLite file, separate from
    # DATABASE_URL, so runs can pause/resume even if the main database is unavailable.
    checkpoint_db_path: Path = DATA_DIR / "checkpoints.db"
    # How many times the evaluator may send tasks back for another round.
    max_evaluation_rounds: int = Field(default=1, ge=0, le=5)

    # ---------- Self-evaluation (Phase 9) ----------
    # llm = rules + evidence check + LLM judge (1 extra call); rules = no LLM judge.
    evaluation_mode: Literal["llm", "rules"] = "llm"
    # A completed task the judge scores below this (0-10) is sent back with feedback.
    judge_pass_score: int = Field(default=5, ge=0, le=10)
    # How many times the agent may throw the plan away and plan again.
    max_replans: int = Field(default=1, ge=0, le=3)
    # LangGraph's guard against infinite graph loops (each node visit = 1 super-step).
    graph_recursion_limit: int = Field(default=100, ge=10, le=1_000)

    # ---------- Safety & permissions (Phase 10) ----------
    # Tools switched off completely, e.g. DISABLED_TOOLS=["python_exec"] (JSON list in .env).
    disabled_tools: list[str] = Field(default_factory=list)
    # send_email may ONLY write to these: exact addresses or whole domains ("@mycollege.edu").
    # Empty = no recipient is allowed, so every email is denied (safe default).
    email_allowed_recipients: list[str] = Field(default_factory=list)
    # Outbox mode: emails are saved as .eml files here instead of being sent.
    email_outbox_dir: Path = DATA_DIR / "outbox"
    # Email delivery mode: "outbox" (writes to outbox_dir) or "gmail" (actual delivery via Gmail API)
    email_mode: Literal["outbox", "gmail"] = Field(default="outbox")
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:8000/api/email/oauth/callback"
    google_token_encryption_key: SecretStr | None = None
    gmail_access_token: SecretStr | None = None
    gmail_refresh_token: SecretStr | None = None
    # Max calls per tool per minute, across all runs (protects APIs from hammering).
    tool_rate_limits_per_minute: dict[str, int] = Field(
        default_factory=lambda: {"web_search": 20, "python_exec": 10, "send_email": 5}
    )
    # Max calls per tool within ONE run (stops a confused or manipulated agent early).
    tool_budgets_per_run: dict[str, int] = Field(
        default_factory=lambda: {"web_search": 20, "python_exec": 8, "send_email": 3}
    )
    # Flag outside content that looks like instructions aimed at the AI.
    injection_scan_enabled: bool = True

    # ---------- Authentication & API (Phase 12) ----------
    # Signs access tokens. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(64))"
    # Empty in development = a random key per server start (everyone is logged out on
    # restart). Production refuses to start without one.
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    # Short-lived access tokens limit the damage of a stolen token; refresh tokens
    # (stored hashed in the database, rotated on every use) keep users logged in.
    access_token_minutes: int = Field(
        default=15,
        ge=1,
        le=365 * 24 * 60,
        validation_alias=AliasChoices("access_token_minutes", "jwt_access_token_expire_minutes"),
    )
    refresh_token_days: int = Field(default=7, ge=1, le=90)
    # Anyone may create an account (fine for a personal deployment you control).
    allow_registration: bool = True
    # Brute-force protection: this many failed logins per email+IP within the window
    # -> HTTP 429 until the window passes.
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_window_minutes: int = Field(default=15, ge=1, le=24 * 60)
    # Browser apps on OTHER origins allowed to call the API. The Next.js dashboard
    # (Phase 13) proxies /api through its own server, so it is same-origin and doesn't
    # need this; it's for calling the API directly from a page on another port/domain.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])

    @model_validator(mode="after")
    def _require_jwt_secret_in_production(self) -> "Settings":
        if self.environment == "production":
            key = self.jwt_secret_key.get_secret_value() if self.jwt_secret_key else ""
            if len(key) < 32:
                raise ValueError("JWT_SECRET_KEY (32+ characters) is required when ENVIRONMENT=production.")
        return self

    @property
    def llm_api_key_configured(self) -> bool:
        """True if the API key for the *selected* provider is present.

        Reports only yes/no, never the key itself, so it is safe to show in /health.
        """
        key = self.google_api_key if self.llm_provider == "gemini" else self.openai_api_key
        return key is not None and bool(key.get_secret_value().strip())

    @property
    def active_model(self) -> str:
        """Model name for the currently selected provider."""
        return self.gemini_model if self.llm_provider == "gemini" else self.openai_model

    @property
    def fallback_models(self) -> list[str]:
        """Backup models for the selected provider (never repeats the main model)."""
        models = self.gemini_fallback_models if self.llm_provider == "gemini" else self.openai_fallback_models
        return [m for m in dict.fromkeys(models) if m and m != self.active_model]


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance.

    @lru_cache means the .env file is read once, on the first call; later calls
    return the cached object. FastAPI also uses this function as a dependency,
    so tests can swap in fake settings with app.dependency_overrides.
    """
    return Settings()
