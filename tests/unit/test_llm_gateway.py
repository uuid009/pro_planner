from app.config import Settings
from app.models.providers import chat_complete, openai_compatible_base, probe_llm


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://postgres:secret@127.0.0.1:5432/mydb",
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "llm_base_url": "http://127.0.0.1:8001/v1",
    }
    values.update(overrides)
    return Settings(**values)


def test_openai_compatible_base_appends_v1_once():
    assert openai_compatible_base("http://127.0.0.1:8001") == "http://127.0.0.1:8001/v1"
    assert openai_compatible_base("http://127.0.0.1:8001/v1/") == "http://127.0.0.1:8001/v1"


def test_mock_chat_is_explicitly_labeled():
    text = chat_complete(_settings(), [{"role": "user", "content": "你好"}])
    assert "Mock" in text


def test_mock_probe_is_not_checked():
    assert probe_llm(_settings()) == {"ready": False, "checked": False, "detail": "mock"}
