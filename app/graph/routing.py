"""条件边。控制流放在这里，不藏在 Agent 函数内部。"""

from __future__ import annotations

from app.config import get_settings
from app.graph.state import WorkflowState


def route_after_missing_check(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "fail"
    if state.get("missing_information"):
        return "human_clarification"
    return "retrieve_evidence"


def route_after_evidence(state: WorkflowState) -> str | list[str]:
    if state.get("status") == "failed":
        return "fail"
    return ["generate_proposal", "generate_plan"]


def route_after_audit(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "fail"
    report = state.get("audit_report") or {}
    if report.get("passed"):
        return "human_approval"
    if int(state.get("revision_count") or 0) >= get_settings().max_revision_rounds:
        return "human_approval"
    return "revise_output"


def route_after_review(state: WorkflowState) -> str:
    decision = (state.get("review_decision") or {}).get("decision")
    if decision == "approve":
        return "done"
    if decision == "request_information":
        return "human_clarification"
    if decision == "select_option":
        return "done"
    return "revise_output"
