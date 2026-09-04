"""Application configuration."""
from typing import Any, List, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings."""
    
    # Application
    app_name: str = "OpenNotebookLM"
    app_port: int = 8000
    app_env: str = "development"
    debug: bool = True
    
    # Database
    db_path: str = "./data/opennotebook.db"
    database_url: str = "sqlite:///./data/opennotebook.db"
    ingestion_worker_concurrency: int = Field(default=1, ge=1, le=16)
    
    # Embedding
    # Multilingual, unlike the English-only bge-small it replaced. Chosen over
    # bge-m3 on memory: bge-m3 peaks at ~4.85 GB RSS against ~2.69 GB here, which
    # OOM-killed a full re-index on an 8 GB host. Changing this invalidates every
    # stored vector — see "Embeddings" in the README before switching.
    emb_backend: str = "sqlitevec"  # sqlitevec or faiss
    emb_model_name: str = "intfloat/multilingual-e5-base"
    emb_dimension: int = 768  # corrected from the loaded model at startup
    
    # LLM
    # "auto" uses the first provider that is actually configured: Claude, then
    # OpenAI, then a local OpenAI-compatible server. Name one to pin it.
    llm_mode: str = "auto"  # auto, claude, openai, local, or none
    local_model_path: str = "./models/phi-2.gguf"  # unused; the local path talks HTTP
    local_model_context_size: int = 2048
    local_model_max_tokens: int = 512

    # Local OpenAI-compatible server (Ollama, llama.cpp, vLLM, ...)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.2"  # must match a model you have pulled

    # Cloud APIs
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-5.6"
    # Point the OpenAI path at any provider speaking the same chat-completions
    # API — Groq, OpenRouter, DeepSeek, Gemini's compatibility layer — by giving
    # its /v1 endpoint here. None means OpenAI itself. The `openai` SDK also
    # honours an OPENAI_BASE_URL in the environment, so leaving this unset is
    # not the same as forcing OpenAI; set it explicitly to be sure.
    openai_base_url: Optional[str] = None
    # Groq extension, for its reasoning models. Left unset, a model such as
    # qwen3.6-27b returns its whole chain of thought inside the answer, wrapped
    # in <think> tags. "hidden" drops it, "parsed" moves it to a separate field,
    # "raw" is the provider default. The reasoning is generated either way and
    # is charged against the request's max_tokens, so a non-reasoning model
    # stays the cheaper way to get a clean answer. Only send this to a provider
    # that understands it — OpenAI itself rejects unknown parameters.
    openai_reasoning_format: Optional[str] = None  # parsed, raw, or hidden
    # A reasoning model spends this budget on thinking before it writes the
    # answer, so too small a value truncates the reply rather than the thinking
    # — measured on Groq's qwen3.6-27b, turns that reasoned for the whole 512
    # services/rag.py sends came back cut mid-sentence or empty. A request's
    # max_tokens is raised to this floor, never lowered to it, and a
    # non-reasoning model is unaffected: it stops when the answer ends.
    openai_min_max_tokens: int = 2048
    # What a caller gets when it asks for as much as the model will give rather
    # than naming a number. Left unset, the limit is read from the provider —
    # OpenAI-compatible `/v1/models` reports `max_completion_tokens`, so this
    # never becomes a table of model sizes maintained by hand. Omitting
    # max_tokens from the request is not the same thing and is not the answer:
    # Groq then applies its own 2048 default and truncates the reply.
    llm_max_output_tokens: Optional[int] = None
    # Ceiling on one request's prompt *plus* its max_tokens. Providers count
    # both against a rate limit and refuse the whole request before the model
    # sees it: Groq's on-demand tier allows 8000 a minute, which qwen3.6-27b's
    # own 16384-token output limit cannot fit under, so asking for the model's
    # limit there is a 413 every time. Left unset, the ceiling is learned from
    # the first refusal that names one, so the default needs no tuning. Set it
    # to skip that refusal, which each feature otherwise pays once.
    llm_max_request_tokens: Optional[int] = None

    claude_api_key: Optional[str] = None
    claude_model: str = "claude-opus-5"
    # Answering from retrieved chunks is not a reasoning-heavy task, so the
    # default trades depth for latency. Raise it for harder corpora.
    claude_effort: str = "low"  # low, medium, high, xhigh, max
    # Thinking is on by default on current Claude models and shares the output
    # budget with the answer, so a caller's max_tokens is raised to this floor.
    claude_min_max_tokens: int = 2048
    # What a caller asking for the model's limit gets on the Claude path, which
    # cannot discover it the way the OpenAI path does: the Messages API requires
    # max_tokens, and while current models accept up to 128k, the SDK needs
    # streaming above roughly this to stay inside its HTTP timeout — and nothing
    # here streams. So this is the practical non-streaming ceiling, not the
    # model's headline figure.
    claude_max_output_tokens: int = 16000
    
    # YouTube
    enable_yt_transcription: bool = True
    yt_api_key: Optional[str] = None
    yt_whisper_fallback_enabled: bool = True
    yt_whisper_model: str = "base"
    yt_max_duration_seconds: int = 1800
    yt_whisper_cache_dir: str = "./models/whisper"
    
    # File Upload
    max_file_size_mb: int = 50
    allowed_file_types: str = "pdf,txt,md"
    max_url_download_mb: int = 10
    max_url_redirects: int = 5
    url_connect_timeout_seconds: int = 5
    url_read_timeout_seconds: int = 30
    url_download_timeout_seconds: int = 30
    
    # Security
    secret_key: str = "change-this-secret-key-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # Authentication
    # No default: a deployment must supply its own signing key. Development
    # falls back to a per-process random key (see services.auth).
    jwt_secret_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    allow_public_registration: Optional[bool] = None

    # A demo account the deployment keeps present so a fresh database is not a
    # locked door. Its credentials are published on the sign-in page, so any
    # deployment reachable by anyone else must set SEED_DEMO_USER=false.
    seed_demo_user: bool = True
    demo_username: str = "demo"
    demo_email: str = "demo@example.com"
    demo_password: str = "demo1234"

    # Monitoring
    enable_metrics: bool = True
    log_level: str = "INFO"
    log_format: str = "json"
    
    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_period: int = 60
    rate_limit_max_keys: int = 10000
    trust_proxy_headers: bool = False

    # Cache
    redis_url: Optional[str] = None
    # Compose consumes this value for Redis itself. It is declared here too so
    # copying the canonical .env example cannot fail Settings extra-key checks.
    redis_maxmemory: str = "256mb"
    cache_namespace: str = "opennotebooklm"
    # Separate bounds: at most this many cached values and this many scope
    # version markers. They are reported independently by CacheService stats.
    cache_max_entries: int = 10000
    
    # Chunking
    chunk_size: int = Field(default=512, ge=1)
    chunk_overlap: int = 50
    max_chunks_per_doc: int = 1000
    
    # Retrieval
    retrieval_top_k: int = 5
    # Candidates pulled from each retriever before fusion. Replaces a
    # hardcoded `top_k * 2`, which left the ranker almost nothing to choose
    # between.
    retrieval_candidate_k: int = 30
    # Minimum cosine similarity for a dense candidate. Zero by default:
    # measured e5 similarities sit between 0.67 and 0.71 whether a chunk is
    # relevant or not, so any cut inside that band is arbitrary -- and the
    # 0.5 that used to be hardcoded here filtered nothing at all.
    retrieval_min_score: float = 0.0
    # Hybrid dense + BM25 retrieval, fused by reciprocal rank. Costs no extra
    # memory, which is what makes it the usable lever on a small host.
    hybrid_enabled: bool = True
    hybrid_rrf_k: int = 60
    # Jaccard token overlap at which two candidates are the same passage.
    dedupe_jaccard: float = 0.9
    # Legacy heuristic reranker. Only consulted when hybrid_enabled is false;
    # its keyword term scores zero for CJK text.
    rerank_enabled: bool = True
    rerank_alpha: float = 0.7
    rerank_beta: float = 0.2
    rerank_gamma: float = 0.1
    # Ceiling on the characters of retrieved context put in a prompt. Counted
    # in characters rather than tokens on purpose: it needs no tokenizer and
    # is conservative for Latin text, where a character is well under a token.
    context_char_budget: int = 12000

    @field_validator(
        "llm_max_output_tokens", "llm_max_request_tokens", mode="before",
    )
    @classmethod
    def _blank_means_unset(cls, value: Any) -> Any:
        """Read a blank value as unset rather than as a broken number.

        These two are documented in `.env.example` as optional, and the natural
        way to write an optional setting in a dotenv file is to leave the key
        with nothing after the `=`. For a string field pydantic accepts that; for
        a number it is a validation error, which stops the process from starting
        over a blank line nobody would read as a mistake.

        Args:
            value: The raw environment value.

        Returns:
            None for a blank value, otherwise the value unchanged, for the
            normal parsing to handle.
        """
        if isinstance(value, str) and not value.strip():
            return None

        return value

    @model_validator(mode="after")
    def _default_registration_by_environment(self):
        """Open enrollment only for development when no override is supplied.

        Returns:
            Settings with a concrete public-registration policy.
        """
        if self.allow_public_registration is None:
            self.allow_public_registration = self.app_env == "development"
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property
    def allowed_file_types_list(self) -> List[str]:
        """Parse allowed file types from comma-separated string."""
        return [ext.strip() for ext in self.allowed_file_types.split(",")]
    
    @property
    def max_file_size_bytes(self) -> int:
        """Convert MB to bytes."""
        return self.max_file_size_mb * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
