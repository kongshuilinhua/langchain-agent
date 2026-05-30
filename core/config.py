from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Lingshu Agent"
    app_version: str = "0.1.0"
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24
    api_key_encryption_key: str | None = Field(default=None, alias="API_KEY_ENCRYPTION_KEY")
    invite_api_enabled: bool = Field(default=False, alias="INVITE_API_ENABLED")
    cors_origins: str = Field(default="http://127.0.0.1:5174,http://localhost:5174", alias="CORS_ORIGINS")

    database_url: str = Field(
        default="postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent",
        alias="DATABASE_URL",
    )
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    openai_api_base: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", alias="OPENAI_API_BASE")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="qwen-plus", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-v4", alias="OPENAI_EMBEDDING_MODEL")
    dashscope_api_key: str | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    deepseek_api_base: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_API_BASE")
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    embedding_api_base: str | None = Field(default=None, alias="EMBEDDING_API_BASE")
    embedding_api_key: str | None = Field(default=None, alias="EMBEDDING_API_KEY")
    rerank_api_base: str | None = Field(default=None, alias="RERANK_API_BASE")
    rerank_api_key: str | None = Field(default=None, alias="RERANK_API_KEY")
    health_model_probe_enabled: bool = Field(default=True, alias="HEALTH_MODEL_PROBE_ENABLED")
    mock_llm: bool = Field(default=False, validation_alias=AliasChoices("LINGSHU_MOCK_LLM", "SWEEPER_MOCK_LLM"))

    milvus_uri: str = Field(default="http://192.168.150.101:19530", alias="MILVUS_URI")
    milvus_token: str | None = Field(default=None, alias="MILVUS_TOKEN")
    milvus_collection: str = Field(default="lingshu_chunks", alias="MILVUS_COLLECTION")
    milvus_dimension: int | None = Field(default=None, alias="MILVUS_DIMENSION")
    vector_backend: str = Field(default="memory", validation_alias=AliasChoices("LINGSHU_VECTOR_BACKEND", "SWEEPER_VECTOR_BACKEND"))

    rag_top_k: int = Field(default=4, alias="RAG_TOP_K")
    rag_dense_top_k: int = Field(default=12, alias="RAG_DENSE_TOP_K")
    rag_bm25_top_k: int = Field(default=12, alias="RAG_BM25_TOP_K")
    rag_rrf_k: int = Field(default=60, alias="RAG_RRF_K")
    rag_rerank_enabled: bool = Field(default=True, alias="RAG_RERANK_ENABLED")
    rag_rerank_model: str = Field(default="qwen3-rerank", alias="RAG_RERANK_MODEL")
    rag_rerank_top_n: int = Field(default=6, alias="RAG_RERANK_TOP_N")
    rag_cache_enabled: bool = Field(default=True, alias="RAG_CACHE_ENABLED")
    rag_cache_ttl_seconds: int = Field(default=3600, alias="RAG_CACHE_TTL_SECONDS")
    rag_refuse_when_no_evidence: bool = Field(default=True, alias="RAG_REFUSE_WHEN_NO_EVIDENCE")

    web_search_enabled: bool = Field(default=True, alias="WEB_SEARCH_ENABLED")
    web_search_provider: str = Field(default="duckduckgo_html", alias="WEB_SEARCH_PROVIDER")
    web_search_top_k: int = Field(default=5, alias="WEB_SEARCH_TOP_K")
    web_search_timeout_seconds: int = Field(default=8, alias="WEB_SEARCH_TIMEOUT_SECONDS")
    web_search_max_response_bytes: int = Field(default=512 * 1024, alias="WEB_SEARCH_MAX_RESPONSE_BYTES")
    web_search_user_agent: str = Field(default="LingshuAgent/0.1 (+https://local.lingshu.agent)", alias="WEB_SEARCH_USER_AGENT")

    upload_max_bytes: int = Field(default=8 * 1024 * 1024, alias="UPLOAD_MAX_BYTES")

    data_dir: Path = Path("data")
    upload_dir: Path = Path("storage/uploads")

    @field_validator("milvus_dimension", mode="before")
    @classmethod
    def empty_dimension_is_none(cls, value):
        if value == "":
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
