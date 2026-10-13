import pytest
from pydantic import ValidationError

from app.config import Settings


def _base(**overrides) -> dict:
    values = {
        "database_url": "postgresql://postgres:secret@127.0.0.1:5432/mydb",
        "llm_provider": "ollama",
        "llm_base_url": "http://127.0.0.1:11434",
        "embedding_provider": "ollama",
        "embedding_base_url": "http://127.0.0.1:11434",
        "embedding_dimension": 1024,
        "chunk_size": 800,
        "chunk_overlap": 120,
    }
    values.update(overrides)
    return values


def test_local_ollama_settings_are_accepted():
    settings = Settings(**_base())
    assert settings.llm_provider == "ollama"
    assert settings.mock_mode is False
    assert settings.embedding_dimension == 1024


def test_vllm_and_local_embedding_settings_are_accepted():
    settings = Settings(
        **_base(
            llm_provider="openai_compatible",
            llm_base_url="http://127.0.0.1:8001/v1",
            llm_model="Qwen3.8-27B-FP8",
            embedding_provider="local",
            embedding_model="models/bge-m3",
            embedding_base_url="http://unused.invalid",
        )
    )
    assert settings.llm_provider == "openai_compatible"
    assert settings.embedding_provider == "local"
    assert settings.mock_mode is False


def test_llm_provider_local_is_rejected():
    with pytest.raises(ValidationError, match="openai_compatible"):
        Settings(**_base(llm_provider="local"))


def test_explicit_mock_provider_is_visible():
    settings = Settings(**_base(llm_provider="mock", embedding_provider="mock"))
    assert settings.llm_mock is True
    assert settings.embedding_mock is True
    assert settings.mock_mode is True


def test_mock_provider_does_not_require_a_local_model_url():
    settings = Settings(
        **_base(
            llm_provider="mock",
            llm_base_url="http://unused.invalid",
            embedding_provider="mock",
            embedding_base_url="http://unused.invalid",
        )
    )
    assert settings.mock_mode is True


def test_cloud_llm_endpoint_is_rejected():
    with pytest.raises(ValidationError, match="云端模型服务"):
        Settings(**_base(llm_base_url="https://api.openai.com/v1"))


def test_azure_openai_endpoint_is_rejected():
    with pytest.raises(ValidationError, match="云端模型服务"):
        Settings(**_base(llm_base_url="https://example.openai.azure.com/openai"))


def test_cloud_embedding_endpoint_is_rejected():
    with pytest.raises(ValidationError, match="EMBEDDING_BASE_URL"):
        Settings(**_base(embedding_base_url="https://api.openai.com/v1"))


def test_chunk_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        Settings(**_base(chunk_size=100, chunk_overlap=100))


def test_embedding_dimension_must_be_positive():
    with pytest.raises(ValidationError, match="EMBEDDING_DIMENSION"):
        Settings(**_base(embedding_dimension=0))


def test_embedding_dimension_must_match_vector_column():
    with pytest.raises(ValidationError, match="向量列维度"):
        Settings(**_base(embedding_dimension=768))
