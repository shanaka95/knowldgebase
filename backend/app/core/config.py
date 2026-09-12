import warnings
from typing import Literal, Self

from pydantic import (
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models_config import model_setting


def _parser_backend() -> Literal["auto", "mineru", "llm"]:
    """Default for IMPORT_PARSER, from ``[parser].backend`` in models.toml."""
    value = str(model_setting("parser", "backend", "auto")).lower()
    return value if value in ("auto", "mineru", "llm") else "auto"  # type: ignore[return-value]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str
    DATABASE_URL: PostgresDsn

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # --- Product identity ----------------------------------------------------
    # Used in emails and anywhere the product names itself to a person.
    APP_NAME: str = "PlusGPT"
    APP_TAGLINE: str = "a personal knowledge management system"

    # --- Email (AWS SES) -----------------------------------------------------
    # Registration, two-factor codes and password resets all depend on email, so
    # a deployment without it can only be used by accounts that already exist.
    # EMAIL_ENABLED=false keeps development and tests offline: codes are written
    # to the log instead of sent.
    EMAIL_ENABLED: bool = False
    EMAIL_FROM: str = "noreply@plusgpt.io"
    EMAIL_FROM_NAME: str = "PlusGPT"
    AWS_REGION: str = "eu-west-1"
    AWS_ACCESS_KEY: str = ""
    AWS_ACCESS_SECRET: str = ""
    EMAIL_TIMEOUT_SECONDS: float = 15.0

    # --- Account security ----------------------------------------------------
    # Every login is confirmed with a code emailed to the account's address.
    TWO_FACTOR_CODE_LENGTH: int = 6
    TWO_FACTOR_TTL_MINUTES: int = 10
    # A login challenge is worthless on its own, but it should not outlive the
    # code it is waiting for.
    LOGIN_CHALLENGE_TTL_MINUTES: int = 15
    EMAIL_VERIFICATION_TTL_HOURS: int = 48
    PASSWORD_RESET_TTL_MINUTES: int = 60
    # Guessing budget for one emailed code before it is destroyed.
    AUTH_CODE_MAX_ATTEMPTS: int = 5
    # How many codes of one kind may be requested in the window, so the mailbox
    # of a known address cannot be used as a weapon.
    AUTH_CODE_MAX_SENDS: int = 5
    AUTH_CODE_SEND_WINDOW_MINUTES: int = 15
    # Failed password attempts before the account stops answering for a while.
    LOGIN_MAX_FAILURES: int = 10
    LOGIN_FAILURE_WINDOW_MINUTES: int = 15
    LOGIN_LOCKOUT_MINUTES: int = 15

    # --- Sharing --------------------------------------------------------------
    # How long an invitation to someone without an account stays good. Long
    # enough to survive a holiday, short enough that a forwarded mailbox from
    # last year is not a way in.
    SHARE_INVITE_TTL_DAYS: int = 14
    # Addresses one share request may name at once.
    SHARE_MAX_RECIPIENTS: int = 50

    # --- API keys -----------------------------------------------------------
    API_KEY_PREFIX: str = "kb_"

    # --- Vector store (Qdrant) ----------------------------------------------
    QDRANT_URL: HttpUrl = HttpUrl("http://localhost:6333")
    QDRANT_COLLECTION: str = "kb_documents"
    QDRANT_TIMEOUT_SECONDS: float = 10.0
    # Qdrant holds every user's embeddings and the payloads beside them, and it
    # answers anyone who can reach it. On a single host that is "anything else
    # on the container network", which is not the same as nobody. Empty in
    # development, where nothing else is on the network.
    QDRANT_API_KEY: str = ""

    # --- Object storage (MinIO) ---------------------------------------------
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "kb-attachments"
    MINIO_SECURE: bool = False
    MAX_UPLOAD_SIZE_MB: int = 25

    # --- Embedding model (OpenAI-compatible; defaults from models.toml) -----
    EMBEDDING_BASE_URL: HttpUrl = Field(
        default_factory=lambda: HttpUrl(
            str(model_setting("embeddings", "base_url", "http://127.0.0.1:8080/v1"))
        )
    )
    EMBEDDING_MODEL: str = Field(
        default_factory=lambda: str(
            model_setting(
                "embeddings",
                "model",
                "jinaai/jina-embeddings-v5-text-small-retrieval-mlx",
            )
        )
    )
    EMBEDDING_API_KEY: str = Field(
        default_factory=lambda: str(model_setting("embeddings", "api_key", "") or "")
    )
    EMBEDDING_DIM: int = Field(
        default_factory=lambda: int(model_setting("embeddings", "dimensions", 1024))
    )
    EMBEDDING_BATCH_SIZE: int = Field(
        default_factory=lambda: int(model_setting("embeddings", "batch_size", 16))
    )
    # How much of a document is fed to the embedding model. This is a property
    # of the deployed model, not of the app: the local Jina model takes a few
    # thousand tokens, while qwen3-embedding-8b takes 32k. Characters rather
    # than tokens because that is what the providers actually enforce.
    EMBEDDING_MAX_CHARS: int = Field(
        default_factory=lambda: int(model_setting("embeddings", "max_chars", 24000))
    )
    EMBEDDING_TIMEOUT_SECONDS: float = Field(
        default_factory=lambda: float(
            model_setting("embeddings", "timeout_seconds", 180.0)
        )
    )

    # --- LLM used for semantic chunking + summaries -------------------------
    LLM_BASE_URL: HttpUrl = Field(
        default_factory=lambda: HttpUrl(
            str(model_setting("llm", "base_url", "http://127.0.0.1:8080/v1"))
        )
    )
    LLM_MODEL: str = Field(
        default_factory=lambda: str(
            model_setting("llm", "model", "lmstudio-community/Qwen3.5-9B-MLX-4bit")
        )
    )
    LLM_API_KEY: str = Field(
        default_factory=lambda: str(model_setting("llm", "api_key", "") or "")
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default_factory=lambda: float(model_setting("llm", "timeout_seconds", 300.0))
    )
    # Largest slice of a document sent to the chat model in one call. Anything
    # longer is summarised window by window, which is slower and loses the
    # thread, so a model with a big context should set this high enough that
    # ordinary documents go through in a single pass.
    LLM_WINDOW_CHARS: int = Field(
        default_factory=lambda: int(model_setting("llm", "window_chars", 20000))
    )
    # Ceiling for the larger retry when a model returns an empty completion
    # because it spent everything on hidden reasoning.
    LLM_MAX_OUTPUT_TOKENS: int = Field(
        default_factory=lambda: int(model_setting("llm", "max_output_tokens", 8192))
    )
    LLM_DISABLE_THINKING: bool = Field(
        default_factory=lambda: bool(model_setting("llm", "disable_thinking", True))
    )
    LLM_TEMPERATURE: float = Field(
        default_factory=lambda: float(model_setting("llm", "temperature", 0.1))
    )
    LLM_MIN_CHARS_FOR_CHUNKING: int = 600
    # how long clients keep retrying "connection refused"/503 while vMLX loads a model
    MODEL_SERVER_COLD_START_SECONDS: float = 150.0

    # --- Document import (PDF / image -> document) --------------------------
    # MinerU2.5 is a document-parsing VLM. vMLX cannot load it (its bundled
    # mlx-vlm predates the qwen2_vl vision stack), so it runs in its own small
    # server: scripts/mineru-server.sh. Defaults come from models.toml [parser].
    # "auto" tries MinerU and falls back to the chat model; "mineru" requires it;
    # "llm" skips it entirely, which is what a deployment without a MinerU server
    # (any hosted provider) wants.
    IMPORT_PARSER: Literal["auto", "mineru", "llm"] = _parser_backend()
    MINERU_BASE_URL: HttpUrl = Field(
        default_factory=lambda: HttpUrl(
            str(model_setting("parser", "base_url", "http://127.0.0.1:8010/v1"))
        )
    )
    MINERU_MODEL: str = Field(
        default_factory=lambda: str(
            model_setting("parser", "model", "MinerU2.5-Pro-2605-1.2B")
        )
    )
    MINERU_API_KEY: str = Field(
        default_factory=lambda: str(model_setting("parser", "api_key", "") or "")
    )
    MINERU_TIMEOUT_SECONDS: float = Field(
        default_factory=lambda: float(model_setting("parser", "timeout_seconds", 600.0))
    )
    IMPORT_FALLBACK_TO_LLM: bool = Field(
        default_factory=lambda: bool(model_setting("parser", "fallback_to_llm", True))
    )
    IMPORT_PAGE_DPI: int = Field(
        default_factory=lambda: int(model_setting("parser", "page_dpi", 200))
    )
    IMPORT_MAX_PAGES: int = Field(
        default_factory=lambda: int(model_setting("parser", "max_pages", 100))
    )
    MAX_IMPORT_SIZE_MB: int = 50

    # --- Ask (retrieval-augmented answers) -----------------------------------
    ASK_TOP_K: int = 10
    # A long page holds many sections; sending only its best-matching one loses
    # the answer when the question is about a detail elsewhere in the same page.
    ASK_CHUNKS_PER_DOC: int = 4
    ASK_MAX_PASSAGES: int = 16
    # Context budget in characters. Qwen3.5-9B has plenty of window, but a long
    # prompt is a slow prompt, and relevance drops off fast after the top hits.
    ASK_CONTEXT_CHARS: int = 12000
    ASK_PASSAGE_CHARS: int = 2400
    # With a reranker the answering model sees the reranked top few. Without
    # one there is no confidence signal to cut on, so every retrieved page is
    # offered and the context budget does the trimming.
    ASK_DOCUMENTS_WITHOUT_RERANK: int = 10
    ASK_MAX_TOKENS: int = 900
    ASK_TEMPERATURE: float = 0.2

    # --- Reranking -----------------------------------------------------------
    # Fusion decides which pages are worth looking at; a cross-encoder decides
    # which of those actually answer the question. It reads the query and each
    # candidate together, so it catches relevance that neither keyword overlap
    # nor a single embedding can. Leave the model empty to turn it off.
    RERANK_MODEL: str = Field(
        default_factory=lambda: str(model_setting("rerank", "model", "") or "")
    )
    RERANK_BASE_URL: HttpUrl | None = Field(
        default_factory=lambda: (
            HttpUrl(str(model_setting("rerank", "base_url", "")))
            if str(model_setting("rerank", "base_url", "") or "")
            else None
        )
    )
    RERANK_API_KEY: str = Field(
        default_factory=lambda: str(model_setting("rerank", "api_key", "") or "")
    )
    RERANK_TIMEOUT_SECONDS: float = Field(
        default_factory=lambda: float(model_setting("rerank", "timeout_seconds", 30.0))
    )
    # Candidates handed to the reranker. Billing is per call, not per document,
    # so a full pool costs exactly what a short one does.
    RERANK_CANDIDATES: int = 10
    # Below this there is nothing to reorder worth paying for.
    RERANK_MIN_CANDIDATES: int = 3
    # Characters of each candidate sent for scoring. Ten of these must fit the
    # reranker's own context window, which is 32k tokens for Cohere rerank 4.
    RERANK_DOC_CHARS: int = 4000
    RERANK_TOTAL_CHARS: int = 100000
    # How many pages reach the answering model. Three is the default because a
    # fourth rarely adds anything a confident top three missed; the extras are
    # admitted only when the reranker scores them nearly as highly.
    RERANK_KEEP_DEFAULT: int = 3
    RERANK_KEEP_MAX: int = 5
    # An extra page is kept only when it is both *close to* the third page and
    # convincing on its own. Both conditions are needed, and the second does most
    # of the work: measured against this reranker, irrelevant pages cluster
    # tightly (0.10-0.21) and score ~0.85 of each other, so a ratio test alone
    # would wave through a run of equally useless pages. Relevant pages sit at
    # 0.25 and above. At a 0.25 floor, 10 of 12 known-relevant pages were kept
    # and none of 18 known-irrelevant ones got in.
    RERANK_KEEP_RATIO: float = 0.8
    RERANK_KEEP_MIN_SCORE: float = 0.25

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.RERANK_MODEL and self.RERANK_BASE_URL)

    # --- Hybrid retrieval ----------------------------------------------------
    RRF_K: int = 60
    RETRIEVAL_CANDIDATES_PER_SOURCE: int = 50
    # Cosine floor for dense hits. Deliberately low: measured scores for genuinely
    # relevant queries reach down to ~0.25 while unrelated text sits near ~0.13,
    # and the two ranges are not cleanly separable, so this only removes obvious
    # noise. Set to 0 to keep every semantic match.
    VECTOR_MIN_SCORE: float = 0.15
    BM25_K1: float = 1.2
    BM25_B: float = 0.75
    BM25_AVG_DOC_LEN: float = 256.0

    # --- Background worker ---------------------------------------------------
    WORKER_CONCURRENCY: int = 2
    # Imports are VLM-bound and slow; keep them off the embedding budget.
    IMPORT_CONCURRENCY: int = 1
    WORKER_POLL_INTERVAL_SECONDS: float = 1.0
    WORKER_LEASE_SECONDS: int = 60
    WORKER_HEARTBEAT_SECONDS: int = 5
    WORKER_OFFLINE_AFTER_SECONDS: int = 30
    WORKER_HEARTBEAT_FILE: str = "/tmp/worker-heartbeat"
    EMBEDDING_DEBOUNCE_SECONDS: int = 10
    EMBEDDING_MAX_ATTEMPTS: int = 3
    EMBEDDING_RETRY_BACKOFF_SECONDS: int = 30

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]
