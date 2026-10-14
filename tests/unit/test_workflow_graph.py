from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import get_settings
from app.graph.runtime import bind_db, unbind_db
from app.graph.workflow import build_workflow


def _settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    return settings


def _state(**overrides):
    state = {
        "run_id": "00000000-0000-0000-0000-000000000010",
        "project_id": "00000000-0000-0000-0000-000000000011",
        "thread_id": "thread-unit",
        "user_request": "编制园区数字化方案",
        "project_snapshot": {
            "name": "园区数字化",
            "objective": "完成一期系统上线",
            "background": "台账分散",
            "constraints": "不使用云端模型",
            "project_type": "implementation",
            "plan_start_date": "2026-01-01",
            "plan_end_date": "2026-06-30",
            "deliverables": ["项目书", "任务计划"],
        },
        "revision_count": 0,
        "revision_summaries": [],
        "artifact_ids": [],
        "errors": [],
        "node_events": [],
        "status": "running",
        "prompt_version": "phase3-v1",
        "model_metadata": {},
    }
    state.update(overrides)
    return state


def test_mock_graph_pauses_for_human_approval(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr("app.agents.knowledge_agent.hybrid_search", lambda *args, **kwargs: [])
    graph = build_workflow(MemorySaver())
    config = {"configurable": {"thread_id": "thread-unit"}}
    bind_db(object())
    try:
        graph.invoke(_state(), config)
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_approval",)
    assert snapshot.values["proposal_draft"]["mock"] is True
    assert snapshot.values["plan_tasks"]
    assert snapshot.values["audit_report"]["passed"] is True
    nodes = {event["node_name"] for event in snapshot.values["node_events"]}
    assert {"analyze_request", "generate_proposal", "generate_plan", "audit_output"} <= nodes


def test_mock_revision_repairs_invalid_dates_before_approval(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr("app.agents.knowledge_agent.hybrid_search", lambda *args, **kwargs: [])
    graph = build_workflow(MemorySaver())
    config = {"configurable": {"thread_id": "thread-revise"}}
    bind_db(object())
    try:
        graph.invoke(_state(user_request="方案需要修订"), config)
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_approval",)
    assert snapshot.values["revision_count"] == 1
    assert snapshot.values["audit_report"]["passed"] is True
    assert any(event["node_name"] == "revise_output" for event in snapshot.values["node_events"])


def test_approve_resume_ends_without_export(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr("app.agents.knowledge_agent.hybrid_search", lambda *args, **kwargs: [])
    graph = build_workflow(MemorySaver())
    config = {"configurable": {"thread_id": "thread-approve"}}
    bind_db(object())
    try:
        graph.invoke(_state(), config)
        graph.invoke(Command(resume={"decision": "approve", "comment": "同意草稿"}), config)
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    assert snapshot.next == ()
    assert snapshot.values["status"] == "approved_pending_export"
    assert snapshot.values["review_decision"]["decision"] == "approve"


def test_missing_content_pauses_for_clarification(monkeypatch):
    _settings(monkeypatch)
    graph = build_workflow(MemorySaver())
    config = {"configurable": {"thread_id": "thread-missing"}}
    snapshot_state = _state(user_request="")
    snapshot_state["project_snapshot"]["name"] = ""
    snapshot_state["project_snapshot"]["objective"] = ""
    snapshot_state["project_snapshot"]["background"] = ""
    snapshot_state["project_snapshot"]["deliverables"] = []
    snapshot_state["project_snapshot"]["plan_start_date"] = None
    snapshot_state["project_snapshot"]["plan_end_date"] = None
    graph.invoke(snapshot_state, config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_clarification",)
    assert "计划书标题" in snapshot.values["missing_information"]
    assert "计划书大致内容" in snapshot.values["missing_information"]
