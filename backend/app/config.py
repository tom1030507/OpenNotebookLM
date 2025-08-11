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
    emb_backend: str = "sqlitevec"  # sqlitevec or faiss
    emb_model_name: str = "BAAI/bge-small-en-v1.5"
    emb_dimension: int = 384
    
    # LLM
    llm_mode: str = "local"  # local, cloud, or auto
    local_model_path: str = "./models/phi-2.gguf"
    local_model_context_size: int = 2048
    local_model_max_tokens: int = 512
    
    # Cloud APIs
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-3.5-turbo"
    claude_api_key: Optional[str] = None
    claude_model: str = "claude-3-haiku-20240307"
    
    # YouTube
    enable_yt_transcription: bool = True
    yt_api_key: Optional[str] = None
    
    # File Upload
    max_file_size_mb: int = 50
    allowed_file_types: str = "pdf,txt,md"
    
    # Security
    secret_key: str = "change-this-secret-key-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    
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
