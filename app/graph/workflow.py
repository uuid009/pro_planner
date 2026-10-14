"""固定可观察的 LangGraph 流程。导出留到 Phase 5。"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.audit_agent import audit_output, validate_plan
from app.agents.coordinator import analyze_request
from app.agents.knowledge_agent import retrieve_evidence
from app.agents.planning_agent import generate_plan
from app.agents.proposal_agent import generate_proposal
from app.agents.revision_agent import revise_output
from app.config import get_settings
from app.graph.persistence import get_checkpointer
from app.graph.routing import (
    route_after_audit,
    route_after_evidence,
    route_after_missing_check,
    route_after_review,
)
from app.graph.runtime import bound_db, traced
from app.graph.state import PROMPT_VERSION, WorkflowState

_graph = None


def build_workflow(checkpointer: BaseCheckpointSaver):
    graph = StateGraph(WorkflowState)
    graph.add_node("analyze_request", traced("analyze_request", _analyze))
    graph.add_node("check_missing_information", traced("check_missing_information", _check_missing))
    graph.add_node("human_clarification", _human_clarification)
    graph.add_node("retrieve_evidence", traced("retrieve_evidence", _retrieve))
    graph.add_node("assess_evidence", traced("assess_evidence", _assess))
    graph.add_node("generate_proposal", traced("generate_proposal", _proposal))
    graph.add_node("generate_plan", traced("generate_plan", _plan))
    graph.add_node("validate_plan", traced("validate_plan", validate_plan))
    graph.add_node("audit_output", traced("audit_output", _audit))
    graph.add_node("revise_output", traced("revise_output", _revise))
    graph.add_node("human_approval", _human_approval)
    graph.add_node("fail", traced("fail", _fail))

    graph.add_edge(START, "analyze_request")
    graph.add_edge("analyze_request", "check_missing_information")
    graph.add_conditional_edges(
        "check_missing_information",
        route_after_missing_check,
        {
            "human_clarification": "human_clarification",
            "retrieve_evidence": "retrieve_evidence",
            "fail": "fail",
        },
    )
    graph.add_edge("human_clarification", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "assess_evidence")
    graph.add_conditional_edges(
        "assess_evidence",
        route_after_evidence,
        ["generate_proposal", "generate_plan", "fail"],
    )
    graph.add_edge("generate_proposal", "validate_plan")
    graph.add_edge("generate_plan", "validate_plan")
    graph.add_edge("validate_plan", "audit_output")
    graph.add_conditional_edges(
        "audit_output",
        route_after_audit,
        {
            "human_approval": "human_approval",
            "revise_output": "revise_output",
            "fail": "fail",
        },
    )
    graph.add_edge("revise_output", "validate_plan")
    graph.add_conditional_edges(
        "human_approval",
        route_after_review,
        {
            "done": END,
            "revise_output": "revise_output",
            "human_clarification": "human_clarification",
        },
    )
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)


def get_compiled_graph():
    global _graph
    if _graph is None:
        _graph = build_workflow(get_checkpointer())
    return _graph


def reset_compiled_graph() -> None:
    global _graph
    _graph = None


def _analyze(state: WorkflowState) -> dict:
    return analyze_request(state, get_settings())


def _retrieve(state: WorkflowState) -> dict:
    db = bound_db()
    if db is None:
        raise RuntimeError("检索缺少数据库会话")
    return retrieve_evidence(state, db, get_settings())


def _proposal(state: WorkflowState) -> dict:
    return generate_proposal(state, get_settings())


def _plan(state: WorkflowState) -> dict:
    return generate_plan(state, get_settings())


def _audit(state: WorkflowState) -> dict:
    return audit_output(state, get_settings())


def _revise(state: WorkflowState) -> dict:
    return revise_output(state, get_settings())


def _check_missing(state: WorkflowState) -> dict:
    missing = state.get("missing_information") or []
    return {"status": "needs_information" if missing else "brief_complete"}


def _assess(state: WorkflowState) -> dict:
    gaps = ((state.get("evidence_bundle") or {}).get("gaps")) or []
    return {
        "status": "evidence_insufficient" if gaps else "evidence_assessed",
        "model_metadata": {"evidence_gaps": len(gaps)},
    }


def _fail(state: WorkflowState) -> dict:
    return {"status": "failed"}


def _human_clarification(state: WorkflowState) -> dict:
    answer = interrupt(
        {
            "type": "clarification",
            "run_id": state.get("run_id"),
            "missing_information": state.get("missing_information") or [],
        }
    )
    text = ""
    if isinstance(answer, dict):
        text = str(answer.get("information") or answer.get("comment") or "")
    elif answer is not None:
        text = str(answer)
    brief = dict(state.get("project_brief") or {})
    if text:
        brief["supplement"] = text
        if not brief.get("objective"):
            brief["objective"] = text
    return {
        "project_brief": brief,
        "missing_information": [],
        "review_feedback": text,
        "status": "clarified",
    }


def _human_approval(state: WorkflowState) -> dict:
    answer = interrupt(
        {
            "type": "approval",
            "run_id": state.get("run_id"),
            "status": state.get("status"),
            "revision_count": state.get("revision_count") or 0,
            "issue_count": len(((state.get("audit_report") or {}).get("issues")) or []),
            "task_count": len(state.get("plan_tasks") or []),
            "prompt_version": state.get("prompt_version") or PROMPT_VERSION,
        }
    )
    decision = (
        answer if isinstance(answer, dict) else {"decision": "revise", "comment": str(answer)}
    )
    kind = decision.get("decision") or "revise"
    if kind == "approve":
        status = "approved_pending_export"
    elif kind == "select_option":
        status = "option_selected"
    else:
        status = "review_received"
    return {
        "review_decision": {
            "decision": kind,
            "comment": decision.get("comment") or "",
            "selected_option": decision.get("selected_option"),
        },
        "review_feedback": decision.get("comment") or "",
        "status": status,
    }
