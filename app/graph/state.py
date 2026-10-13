"""工作流状态。只保存 ID、摘要和结构化结果，不保存原始文件正文。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

PROMPT_VERSION = "phase3-v1"


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class WorkflowState(TypedDict, total=False):
    run_id: str
    project_id: str
    thread_id: str
    user_request: str
    project_snapshot: dict[str, Any]
    project_brief: dict[str, Any]
    missing_information: list[str]
    retrieval_queries: list[str]
    evidence_bundle: dict[str, Any]
    proposal_draft: dict[str, Any]
    plan_tasks: list[dict[str, Any]]
    plan_validation: list[dict[str, Any]]
    audit_report: dict[str, Any]
    review_decision: dict[str, Any] | None
    review_feedback: str
    revision_count: int
    revision_summaries: Annotated[list[str], operator.add]
    artifact_ids: Annotated[list[str], operator.add]
    status: str
    errors: Annotated[list[str], operator.add]
    node_events: Annotated[list[dict[str, Any]], operator.add]
    model_metadata: Annotated[dict[str, Any], merge_dicts]
    prompt_version: str
