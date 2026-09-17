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

from app.core.models_config import model_setting, names_one_model, task_setting


def _parser_backend() -> Literal["auto", "mineru", "llm"]:
    """Default for IMPORT_PARSER, from ``[parser].backend`` in models.toml."""
    value = str(model_setting("parser", "backend", "auto")).lower()
    return value if value in ("auto", "mineru", "llm") else "auto"  # type: ignore[return-value]


def _task_model(task: str, builtin: str) -> str:
    """Which chat model a task uses, before any environment variable.

    Order: the task's own entry in models.toml, then the single model that file
    names (a local server serves one, and asking it for another would only
    404), then the task's built-in default.
    """
    explicit = task_setting(task, "model")
    if explicit:
        return str(explicit)
    if names_one_model():
        return str(model_setting("llm", "model"))
    return builtin


def _task_fallbacks(task: str, builtin: str) -> str:
    """Models to try when the first one fails, comma-separated.

    A deployment pointed at one local server has nowhere to fall back to, so
    naming one model there means no fallbacks rather than a second model the
    server does not have.
    """
    explicit = task_setting(task, "fallback")
    if explicit:
        return ",".join(explicit) if isinstance(explicit, list) else str(explicit)
    if task_setting(task, "model") or not names_one_model():
        return builtin
    return ""


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

    # --- Account limits -------------------------------------------------------
    # The floor under every limit: what an account gets when neither it, nor its
    # group, nor the default group says otherwise. These exist so that a missing
    # or deleted configuration row can never be read as "no pages allowed" - the
    # resolver falls through to a working number rather than to zero.
    #
    # The values themselves are administered at runtime (see
    # app/services/quota.py); these are the last resort, not the product default.
    MAX_PAGES_PER_USER: int = 100
    # Notes are limited apart from pages. They are cheaper and far more
    # numerous, so one number covering both would either starve the notes or
    # make the page limit meaningless.
    MAX_NOTES_PER_USER: int = 1000
    # Credits an account may spend on model work each calendar month. One
    # credit buys a thousand tokens, or ten embeddings, or ten rerank calls -
    # see app/services/credits.py for why those three are the same unit.
    MONTHLY_CREDITS: int = 1000

    # --- Agent proxy ceilings -----------------------------------------------
    # An agent's shard holds a token that reaches the model provider through
    # us. These bound what one turn can cost, because the shard is the least
    # trusted thing that can spend money here: it runs somebody's prompt.
    AGENT_LLM_MAX_OUTPUT_TOKENS: int = 4096
    # Bytes of JSON one proxied turn may carry. A tool loop with a long history
    # is large; a megabyte of it is somebody probing.
    AGENT_LLM_MAX_BODY_BYTES: int = 1_000_000

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

    # Tried when a call fails and the task has no fallbacks of its own.
    LLM_FALLBACK_MODELS: str = ""

    # --- A model per task ----------------------------------------------------
    # One model for everything is a compromise in both directions: answering a
    # question about a dozen pages wants a stronger model than rewriting one
    # page in another language, and paying answering rates to translate is
    # money for nothing. Each task therefore names its own model and the model
    # to try when that one fails.
    #
    # These defaults are what a hosted deployment gets. A `models.toml` that
    # names a single model - which is what a local server is - overrides all of
    # them, because that server has exactly one model loaded.
    LLM_ANSWER_MODEL: str = Field(
        default_factory=lambda: _task_model("answer", "qwen/qwen3.8-flash")
    )
    LLM_ANSWER_FALLBACK_MODELS: str = Field(
        default_factory=lambda: _task_fallbacks("answer", "qwen/qwen3.7-flash")
    )
    LLM_TRANSLATION_MODEL: str = Field(
        default_factory=lambda: _task_model("translation", "qwen/qwen3.7-flash")
    )
    LLM_TRANSLATION_FALLBACK_MODELS: str = Field(
        default_factory=lambda: _task_fallbacks("translation", "qwen/qwen3.8-flash")
    )
    # Chunking and summarising, in the worker.
    LLM_INDEXING_MODEL: str = Field(
        default_factory=lambda: _task_model("indexing", "qwen/qwen3.8-flash")
    )
    LLM_INDEXING_FALLBACK_MODELS: str = Field(
        default_factory=lambda: _task_fallbacks("indexing", "qwen/qwen3.7-flash")
    )

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
    # Chunks decide which pages are worth reading; they are no longer what gets
    # read. Still fetched, because the best-matching one labels the citation.
    ASK_CHUNKS_PER_DOC: int = 4
    # One passage per page now, so this bounds pages rather than excerpts.
    ASK_MAX_PASSAGES: int = 16
    # Context budget in characters, sized for whole pages rather than excerpts.
    # Roughly 75k tokens at four characters each: comfortable inside the
    # smallest window the answering model is served from, and a fraction of the
    # largest. A long prompt is still a slow prompt, so these are the ceiling -
    # a handful of pages usually lands far below them.
    ASK_CONTEXT_CHARS: int = 300000
    # Large enough that a whole contract or manual arrives intact; a page past
    # this is truncated rather than dropped, and the reader is told.
    ASK_PASSAGE_CHARS: int = 120000
    # With a reranker the answering model sees the reranked top few. Without
    # one there is no confidence signal to cut on, so every retrieved page is
    # offered and the context budget does the trimming.
    # No reranker means no confidence signal to cut on, but whole pages still
    # have to fit a prompt somebody will wait for, so the same three apply.
    ASK_DOCUMENTS_WITHOUT_RERANK: int = 3
    ASK_MAX_TOKENS: int = 900
    ASK_TEMPERATURE: float = 0.2

    # --- Document versions and translations ---------------------------------
    # How many versions of a page are kept. Version 1 is always among them: it
    # is what an imported page's original file corresponds to. Editing a long
    # page over a morning produces a handful of versions, not hundreds, because
    # only a change to the words counts as one.
    DOCUMENT_VERSION_HISTORY: int = 50
    # A translation is written window by window for the same reason a summary
    # is: a page can be longer than any single completion.
    TRANSLATION_WINDOW_CHARS: int = 6000
    TRANSLATION_MAX_TOKENS: int = 4096
    TRANSLATION_TEMPERATURE: float = 0.1
    # Example searches drawn from a person's own pages.
    SEARCH_SUGGESTIONS_PER_USER: int = 50
    SEARCH_SUGGESTIONS_SHOWN: int = 3

    # --- Ask conversations ---------------------------------------------------
    # How many earlier question/answer pairs travel with a follow-up. Three
    # covers the way people actually follow up ("and the second one?", "why?")
    # while keeping the prompt short: the excerpts of earlier turns are never
    # resent, so history costs a few hundred tokens, not a few thousand.
    ASK_HISTORY_TURNS: int = 3
    # Earlier answers are carried as a gist, not in full. The model needs to
    # know what it said, not to re-read it; the sources are re-retrieved anyway.
    ASK_HISTORY_ANSWER_CHARS: int = 700
    ASK_HISTORY_QUESTION_CHARS: int = 500
    # A follow-up shorter than this is assumed to lean on the question before
    # it, and the previous question joins the *retrieval* query so that "and in
    # euros?" still finds the invoice. Generation is unaffected: it gets the
    # real history either way. This replaces the usual condense-with-an-LLM
    # step, which would add a whole round trip to every follow-up.
    ASK_FOLLOWUP_CHARS: int = 80
    # Stored citations keep a preview instead of the whole page.
    ASK_STORED_CITATION_CHARS: int = 600
    ASK_MAX_CONVERSATIONS_PER_USER: int = 500

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
    # One page's share of the reranker's window. Raised when candidates became
    # whole pages rather than matched excerpts: at 4000 a long contract was
    # judged on its first two sections. Ten candidates at 12000 exceed the
    # total below, which fit_to_budget then shares out evenly, so this is a
    # ceiling for a single long page rather than a per-page allocation.
    RERANK_DOC_CHARS: int = 12000
    RERANK_TOTAL_CHARS: int = 100000
    # How many pages reach the answering model. Three is the default because a
    # fourth rarely adds anything a confident top three missed; the extras are
    # admitted only when the reranker scores them nearly as highly.
    RERANK_KEEP_DEFAULT: int = 3
    # Equal to the default, so exactly three pages reach the model. The
    # widening rule below is kept because it is the right shape - a query whose
    # answer is split across near-identical pages loses half of it at a hard
    # cut - but a page now carries its whole text rather than an excerpt, and
    # three whole pages already crowd a prompt. Raise this to let it widen.
    RERANK_KEEP_MAX: int = 3
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

    # --- Agents and channels -------------------------------------------------
    # Where each gateway shard's Hermes profiles live. The backend writes a
    # directory per agent here and the gateway picks it up on the next message:
    # profiles_to_serve() is a live directory read, so no restart is needed.
    HERMES_PROFILES_ROOT: str = "/hermes-profiles"
    # Shards exist to cap the blast radius of any in-process isolation failure,
    # and to keep one gateway's bounded turn pool from becoming everyone's queue.
    HERMES_SHARD_COUNT: int = 1
    # The gateway containers run unprivileged; the backend writes their files
    # as root. These say who should own them afterwards. -1 disables the chown
    # (useful in tests and on a single-uid host).
    HERMES_PROFILE_UID: int = 10001
    HERMES_PROFILE_GID: int = 10001
    # How the gateway reaches the MCP server. In-network, so it never leaves the
    # compose network on the way to the knowledge base.
    HERMES_MCP_URL: str = "http://mcp:8000/mcp"
    # Shared secret the gateway presents when it asks who an inbound sender is.
    AGENT_CONTROL_TOKEN: str = ""
    # Where a shard asks who an inbound sender is. In-network by default.
    AGENT_CONTROL_ROUTE_URL: str = "http://backend:8000/api/v1/agent-control/route"
    # Fernet key encrypting admin channel credentials at rest. Generated with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    CHANNEL_SECRET_KEY: str = ""
    # A link code travels through a messaging app, so it is short-lived.
    CHANNEL_LINK_CODE_TTL_MINUTES: int = 15
    # Per-agent ceiling on outstanding codes, so issuing cannot be used to flood.
    CHANNEL_LINK_CODE_MAX_ACTIVE: int = 5
    # The model the hosted agents run on. Same provider as the knowledge base.
    AGENT_LLM_MODEL: str = "qwen/qwen3.8-flash"
    # Which upstream providers may serve that model, best first. OpenRouter
    # otherwise picks for itself and can land on a throttled endpoint while a
    # healthy one sits idle - and the two differ in context window as well, so
    # this is not only about availability.
    AGENT_LLM_PROVIDER_ORDER: str = "Alibaba,Makora"
    # Tried in order when the primary model is unavailable. qwen3.8-flash is
    # the cheapest thing on the menu and is also the most contended, so a
    # second name keeps conversations alive through a throttled spell.
    # Comma-separated; empty disables fallback entirely.
    AGENT_LLM_FALLBACK_MODELS: str = "openai/gpt-5-mini"
    # Agents reach the model through our own OpenAI-compatible proxy rather
    # than holding a provider key: the real key never lands in a profile .env,
    # each agent's token is revocable on its own, and usage is attributable.
    AGENT_LLM_PROXY_URL: str = "http://backend:8000/api/v1/agent-llm/v1"

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
