"""集中配置。默认只连接本地模型服务，测试通过显式 mock 提供方切换。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 与 document_chunks.embedding 的 vector(N) 一致。更换模型维度必须走迁移。
SCHEMA_EMBEDDING_DIMENSION = 1024

ProviderName = Literal["ollama", "openai_compatible", "mock"]

# 已知云端推理入口。openai_compatible 只允许指向本地 vLLM / Ollama 等服务。
BLOCKED_CLOUD_HOSTS = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        "api.groq.com",
        "api.deepseek.com",
        "openrouter.ai",
        "api.mistral.ai",
        "api.together.xyz",
        "api.fireworks.ai",
        "api.x.ai",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str
    llm_provider: ProviderName = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:7b"
    embedding_provider: ProviderName = "ollama"
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    embedding_base_url: str = "http://127.0.0.1:11434"
    reranker_enabled: bool = False
    reranker_model: str = "bge-reranker-v2-m3"
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_top_k: int = 20
    rerank_top_n: int = 8
    upload_dir: str = "data/uploads"
    artifact_dir: str = "data/artifacts"
    app_env: str = "development"
    log_level: str = "INFO"
    demo_user_id: str = "demo-user"
    max_revision_rounds: int = Field(default=3, ge=1)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)

    @property
    def llm_mock(self) -> bool:
        return self.llm_provider == "mock"

    @property
    def embedding_mock(self) -> bool:
        return self.embedding_provider == "mock"

    @property
    def mock_mode(self) -> bool:
        return self.llm_mock or self.embedding_mock

    @model_validator(mode="after")
    def validate_local_runtime(self) -> "Settings":
        if self.embedding_dimension <= 0:
            raise ValueError("EMBEDDING_DIMENSION 必须为正整数")
        if self.embedding_dimension != SCHEMA_EMBEDDING_DIMENSION:
            raise ValueError(
                "EMBEDDING_DIMENSION 与数据库向量列维度 "
                f"{SCHEMA_EMBEDDING_DIMENSION} 不一致"
            )
        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE 必须为正整数")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须大于等于 0 且小于 CHUNK_SIZE")
        if self.retrieval_top_k < 1:
            raise ValueError("RETRIEVAL_TOP_K 必须大于等于 1")
        if self.rerank_top_n < 1:
            raise ValueError("RERANK_TOP_N 必须大于等于 1")
        _reject_cloud_endpoint("LLM_BASE_URL", self.llm_base_url, self.llm_provider)
        _reject_cloud_endpoint(
            "EMBEDDING_BASE_URL", self.embedding_base_url, self.embedding_provider
        )
        return self


def _reject_cloud_endpoint(field_name: str, url: str, provider: str) -> None:
    if provider == "mock":
        return
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(f"{field_name} 必须是 http(s) 地址")
    if host in BLOCKED_CLOUD_HOSTS or host.endswith(".openai.azure.com"):
        raise ValueError(f"{field_name} 指向云端模型服务，本项目不允许调用云端 API")


@lru_cache
def get_settings() -> Settings:
    return Settings()
