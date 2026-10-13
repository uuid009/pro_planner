from app.config import get_settings
from app.graph.workflow import get_compiled_graph


def _use_mock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "embedding_provider", "mock")


def _project(client):
    response = client.post(
        "/api/projects",
        json={
            "name": "工作流项目",
            "project_type": "implementation",
            "objective": "完成一期系统上线",
            "background": "台账分散",
            "constraints": "只使用本地模型",
            "plan_start_date": "2026-01-01",
            "plan_end_date": "2026-06-30",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_run_pauses_for_review_and_records_events(client, monkeypatch):
    _use_mock(monkeypatch)
    project = _project(client)
    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"user_request": "请编制实施方案", "deliverables": ["项目书", "任务计划"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "awaiting_review"
    assert body["prompt_version"] == "phase3-v1"
    assert body["model_name"] == "mock"
    assert len(body["thread_id"]) == 32

    detail = client.get(f"/api/runs/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "awaiting_review"

    events = client.get(f"/api/runs/{body['id']}/events")
    assert events.status_code == 200, events.text
    names = {item["node_name"] for item in events.json()}
    assert "analyze_request" in names
    assert "audit_output" in names
    assert all(item["error_summary"] is None for item in events.json())

    snapshot = get_compiled_graph().get_state({"configurable": {"thread_id": body["thread_id"]}})
    assert snapshot.next == ("human_approval",)
    assert snapshot.values["run_id"] == body["id"]


def test_run_revision_loop_is_visible(client, monkeypatch):
    _use_mock(monkeypatch)
    project = _project(client)
    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"user_request": "这个方案需要修订", "deliverables": ["项目书"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "awaiting_review"
    names = {item["node_name"] for item in client.get(f"/api/runs/{created.json()['id']}/events").json()}
    assert "revise_output" in names
    assert "validate_plan" in names


def test_missing_project_run_is_not_found(client, monkeypatch):
    _use_mock(monkeypatch)
    missing = client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/runs",
        json={"user_request": "编制方案", "deliverables": ["项目书"]},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"
