from app.config import Settings
from app.rag.embeddings import embed_query, embed_texts


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://postgres:secret@127.0.0.1:5432/mydb",
        llm_provider="mock",
        embedding_provider="mock",
        embedding_dimension=1024,
    )


def test_mock_embedding_is_deterministic_and_normalized():
    settings = _settings()
    first = embed_texts(["一期系统上线"], settings)[0]
    second = embed_texts(["一期系统上线"], settings)[0]
    other = embed_texts(["完全不同的内容"], settings)[0]
    assert first == second
    assert first != other
    assert len(first) == 1024
    assert abs(sum(value * value for value in first) - 1.0) < 1e-6


def test_mock_query_embedding_matches_text_embedding():
    settings = _settings()
    assert embed_query("检索查询", settings) == embed_texts(["检索查询"], settings)[0]
