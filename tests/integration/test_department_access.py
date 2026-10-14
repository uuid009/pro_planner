from app.config import get_settings
from tests.helpers import make_pdf


def _mock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    monkeypatch.setattr(settings, "reranker_enabled", False)


def _login(client, username: str, department: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123", "department": department},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_register_requires_department_and_login_rejects_bad_password(client):
    missing = client.post(
        "/api/auth/register",
        json={"username": "nobody", "password": "password123"},
    )
    assert missing.status_code == 422

    wrong = client.post(
        "/api/auth/login",
        json={"username": "algo-user", "password": "not-the-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_login"


def test_departments_cannot_see_or_upload_each_others_documents(client, monkeypatch):
    _mock(monkeypatch)
    framework = _login(client, "frame-user", "framework")
    private_bytes = make_pdf("算法组内部参数只对本组可见")
    private = client.post(
        "/api/documents/upload",
        files={"file": ("algo.pdf", private_bytes, "application/pdf")},
    )
    assert private.status_code == 200, private.text
    assert private.json()["library"] == "algorithm"
    assert client.post(f"/api/documents/{private.json()['id']}/index").status_code == 200

    hidden_list = client.get("/api/documents", headers=framework)
    assert hidden_list.status_code == 200
    assert private.json()["id"] not in {item["id"] for item in hidden_list.json()}
    hidden_search = client.post(
        "/api/retrieval/search",
        json={"query": "算法组内部参数"},
        headers=framework,
    )
    assert hidden_search.status_code == 200
    assert private.json()["id"] not in {
        item["document_id"] for item in hidden_search.json()["items"]
    }
    hidden_index = client.post(f"/api/documents/{private.json()['id']}/index", headers=framework)
    assert hidden_index.status_code == 404

    denied = client.post(
        "/api/documents/upload",
        files={"file": ("other.pdf", make_pdf("框架组尝试写入算法组"), "application/pdf")},
        data={"library": "algorithm"},
        headers=framework,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "library_forbidden"

    shared = client.post(
        "/api/documents/upload",
        files={"file": ("public.pdf", make_pdf("公共资料库对三个部门开放"), "application/pdf")},
        data={"library": "public"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["library"] == "public"
    assert client.post(f"/api/documents/{shared.json()['id']}/index").status_code == 200
    visible = client.post(
        "/api/retrieval/search",
        json={"query": "公共资料库对三个部门开放"},
        headers=framework,
    )
    assert any(item["document_id"] == shared.json()["id"] for item in visible.json()["items"])

    copied = client.post(
        "/api/documents/upload",
        files={"file": ("copy.pdf", private_bytes, "application/pdf")},
        headers=framework,
    )
    assert copied.status_code == 403
    assert "document_id" not in copied.json()["error"]["details"]


def test_documents_require_login(client):
    token = client.headers["Authorization"]
    del client.headers["Authorization"]
    try:
        response = client.get("/api/documents")
    finally:
        client.headers["Authorization"] = token
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "login_required"
