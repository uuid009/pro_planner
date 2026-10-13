from app.config import get_settings


def _use_mock(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "artifacts"))


def _project(client):
    response = client.post(
        "/api/projects",
        json={
            "name": "审核项目",
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


def _approval_checkpoint(client, run_id: str) -> str:
    history = client.get(f"/api/runs/{run_id}/checkpoints")
    assert history.status_code == 200, history.text
    matches = [item for item in history.json() if "human_approval" in item["next_nodes"]]
    assert matches, history.text
    return matches[0]["checkpoint_id"]


def test_approve_is_idempotent_and_fork_keeps_parent_artifacts(client, monkeypatch, tmp_path):
    _use_mock(monkeypatch, tmp_path)
    project = _project(client)
    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"user_request": "请编制实施方案", "deliverables": ["项目书", "任务计划"]},
    )
    assert created.status_code == 201, created.text
    parent = created.json()
    assert parent["status"] == "awaiting_review"
    checkpoint_id = _approval_checkpoint(client, parent["id"])

    approved = client.post(f"/api/runs/{parent['id']}/resume", json={"decision": "approve"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_pending_export"

    artifacts = client.get(f"/api/projects/{project['id']}/artifacts")
    assert artifacts.status_code == 200, artifacts.text
    assert len(artifacts.json()) == 1
    parent_artifact = artifacts.json()[0]
    assert parent_artifact["run_id"] == parent["id"]
    assert parent_artifact["review_status"] == "demo_approved"
    assert parent_artifact["artifact_type"] == "draft_snapshot"

    downloaded = client.get(f"/api/artifacts/{parent_artifact['id']}/download")
    assert downloaded.status_code == 200
    assert "draft_snapshot" in downloaded.json()["kind"]
    evidence = client.get(f"/api/artifacts/{parent_artifact['id']}/evidence")
    assert evidence.status_code == 200

    again = client.post(f"/api/runs/{parent['id']}/resume", json={"decision": "approve"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "run_not_waiting"
    assert len(client.get(f"/api/projects/{project['id']}/artifacts").json()) == 1

    forked = client.post(
        f"/api/runs/{parent['id']}/fork",
        json={"checkpoint_id": checkpoint_id, "branch_label": "修订分支"},
    )
    assert forked.status_code == 201, forked.text
    child = forked.json()
    assert child["thread_id"] != parent["thread_id"]
    assert child["parent_run_id"] == parent["id"]
    assert child["parent_checkpoint_id"] == checkpoint_id
    assert child["status"] == "awaiting_review"
    assert len(client.get(f"/api/projects/{project['id']}/artifacts").json()) == 1

    revised = client.post(
        f"/api/runs/{child['id']}/resume",
        json={"decision": "revise", "comment": "把实施范围写清楚"},
    )
    assert revised.status_code == 200, revised.text
    review = client.get(f"/api/runs/{child['id']}/review")
    assert review.status_code == 200, review.text
    descriptions = " ".join(task.get("description") or "" for task in review.json()["tasks"])
    assert "修订意见：把实施范围写清楚" in descriptions
    assert review.json()["demo_user_id"] == "demo-user"
    assert len(client.get(f"/api/projects/{project['id']}/artifacts").json()) == 1

    child_approved = client.post(f"/api/runs/{child['id']}/resume", json={"decision": "approve"})
    assert child_approved.status_code == 200, child_approved.text
    listed = client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert len(listed) == 2
    child_rows = [item for item in listed if item["run_id"] == child["id"]]
    parent_rows = [item for item in listed if item["run_id"] == parent["id"]]
    assert len(child_rows) == 1
    assert len(parent_rows) == 1
    assert child_rows[0]["id"] != parent_rows[0]["id"]
    parent_review = client.get(f"/api/runs/{parent['id']}/review").json()
    assert parent_review["approvals"][0]["artifact_version_id"] == parent_artifact["id"]
    assert parent_review["approvals"][0]["decision"] == "approve"


def test_missing_deliverable_can_be_clarified(client, monkeypatch, tmp_path):
    _use_mock(monkeypatch, tmp_path)
    project = _project(client)
    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"user_request": "请编制实施方案", "deliverables": []},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "awaiting_information"

    empty = client.post(f"/api/runs/{created.json()['id']}/resume", json={"information": "  "})
    assert empty.status_code == 422

    resumed = client.post(
        f"/api/runs/{created.json()['id']}/resume",
        json={"information": "交付项目书和任务计划"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "awaiting_review"


def test_revise_requires_comment(client, monkeypatch, tmp_path):
    _use_mock(monkeypatch, tmp_path)
    project = _project(client)
    created = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"user_request": "请编制实施方案", "deliverables": ["项目书"]},
    )
    assert created.status_code == 201, created.text
    rejected = client.post(
        f"/api/runs/{created.json()['id']}/resume",
        json={"decision": "revise", "comment": "  "},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "comment_required"
    assert client.get(f"/api/runs/{created.json()['id']}").json()["status"] == "awaiting_review"
