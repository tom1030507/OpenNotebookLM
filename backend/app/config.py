"""Application configuration."""
from typing import List, Optional
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
    
    # Embedding
    # bge-m3 is multilingual, unlike the English-only bge-small it replaced, and
    # needs no query/passage prefixes. Changing this invalidates every stored
    # vector — see "Embeddings" in the README before switching.
    emb_backend: str = "sqlitevec"  # sqlitevec or faiss
    emb_model_name: str = "BAAI/bge-m3"
    emb_dimension: int = 1024  # corrected from the loaded model at startup
    
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
    claude_api_key: Optional[str] = None
    claude_model: str = "claude-opus-5"
    # Answering from retrieved chunks is not a reasoning-heavy task, so the
    # default trades depth for latency. Raise it for harder corpora.
    claude_effort: str = "low"  # low, medium, high, xhigh, max
    # Thinking is on by default on current Claude models and shares the output
    # budget with the answer, so a caller's max_tokens is raised to this floor.
    claude_min_max_tokens: int = 2048
    
    # YouTube
    enable_yt_transcription: bool = True
    yt_api_key: Optional[str] = None
    
    # File Upload
    max_file_size_mb: int = 50
    allowed_file_types: str = "pdf,txt,md"
    
    # Security
    secret_key: str = "change-this-secret-key-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # Authentication
    # No default: a deployment must supply its own signing key. Development
    # falls back to a per-process random key (see services.auth).
    jwt_secret_key: Optional[str] = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    
    # Monitoring
    enable_metrics: bool = True
    log_level: str = "INFO"
    log_format: str = "json"
    
    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_period: int = 60
    
    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 50
    max_chunks_per_doc: int = 1000
    
    # Retrieval
    retrieval_top_k: int = 5
    rerank_enabled: bool = True
    rerank_alpha: float = 0.7
    rerank_beta: float = 0.2
    rerank_gamma: float = 0.1
    
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
