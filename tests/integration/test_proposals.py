from app.config import get_settings


def _use_mock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "embedding_provider", "mock")


def test_proposal_needs_only_title_and_brief(client, monkeypatch):
    _use_mock(monkeypatch)
    created = client.post(
        "/api/proposals",
        json={"title": "园区数字化计划书", "content_brief": "统一台账并形成可审核的实施方案。"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "awaiting_review"
    assert body["title"] == "园区数字化计划书"
    assert body["mock_mode"] is True

    review = client.get(f"/api/runs/{body['run_id']}/review")
    assert review.status_code == 200, review.text
    headings = {item["heading"] for item in review.json()["sections"]}
    assert "项目概述" in headings
    assert "参考材料与待确认事项" in headings
    assert review.json()["unresolved_items"]


def test_demo_login_uses_selected_group(client):
    entered = client.post("/api/auth/demo", json={"department": "testing"})
    assert entered.status_code == 200, entered.text
    assert entered.json()["user"]["department"] == "testing"
    assert entered.json()["token"]
