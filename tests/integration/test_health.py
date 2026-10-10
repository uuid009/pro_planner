from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health_reports_database_and_pgvector():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["pgvector"]
    assert body["mock_mode"] is False
    assert body["embedding_dimension"] == 1024
    assert "database_url" not in body
    assert "password" not in response.text.lower()


def test_health_does_not_leak_connection_secrets(monkeypatch):
    secret = "super-secret-password"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://postgres:{secret}@127.0.0.1:1/none",
    )
    get_settings.cache_clear()

    def explode(*args, **kwargs):
        raise RuntimeError(f"connect failed for {args[0] if args else kwargs}")

    monkeypatch.setattr("app.main.psycopg.connect", explode)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 503
    assert secret not in response.text
    assert "127.0.0.1:1" not in response.text
    assert response.json()["database_error"] == "RuntimeError"
