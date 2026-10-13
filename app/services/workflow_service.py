"""创建工作流运行并查询状态。恢复、分叉留到 Phase 4。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.db.models import AgentEvent, Project, WorkflowRun
from app.graph.runtime import bind_db, persist_node_events, unbind_db
from app.graph.state import PROMPT_VERSION
from app.graph.workflow import get_compiled_graph


def start_run(db: Session, project_id: UUID, user_request: str, deliverables: list[str]) -> WorkflowRun:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project_not_found", "项目不存在")
    settings = get_settings()
    run = WorkflowRun(
        id=uuid4(),
        project_id=project.id,
        thread_id=secrets.token_hex(16),
        status="running",
        model_name="mock" if settings.llm_mock else settings.llm_model,
        prompt_version=PROMPT_VERSION,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    try:
        graph = get_compiled_graph()
    except RuntimeError as exc:
        run.status = "failed"
        run.error_summary = "checkpointer_unavailable"
        db.commit()
        raise AppError(503, "checkpointer_unavailable", "工作流检查点存储不可用") from exc
    config = {"configurable": {"thread_id": run.thread_id}}
    bind_db(db)
    try:
        graph.invoke(_initial_state(run, project, user_request, deliverables, settings), config)
    except Exception as exc:
        run.status = "failed"
        run.error_summary = type(exc).__name__
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise AppError(500, "workflow_failed", "工作流执行失败", {"error": type(exc).__name__}) from exc
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    persist_node_events(db, run.id, (snapshot.values or {}).get("node_events") or [])
    run.status = status_from_snapshot(snapshot)
    if run.status == "failed":
        errors = (snapshot.values or {}).get("errors") or []
        run.error_summary = "; ".join(errors)[:500] or "failed"
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: UUID) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise AppError(404, "run_not_found", "工作流运行不存在")
    return run


def list_events(db: Session, run_id: UUID) -> list[AgentEvent]:
    get_run(db, run_id)
    return list(
        db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.created_at.asc())
        )
    )


def status_from_snapshot(snapshot) -> str:
    pending = set(snapshot.next or ())
    if "human_approval" in pending:
        return "awaiting_review"
    if "human_clarification" in pending:
        return "awaiting_information"
    values = snapshot.values or {}
    return str(values.get("status") or "unknown")


def _initial_state(run: WorkflowRun, project: Project, user_request: str, deliverables: list[str], settings) -> dict:
    return {
        "run_id": str(run.id),
        "project_id": str(project.id),
        "thread_id": run.thread_id,
        "user_request": user_request.strip(),
        "project_snapshot": {
            "name": project.name,
            "objective": project.objective,
            "background": project.background,
            "constraints": project.constraints,
            "project_type": project.project_type,
            "plan_start_date": project.plan_start_date.isoformat() if project.plan_start_date else None,
            "plan_end_date": project.plan_end_date.isoformat() if project.plan_end_date else None,
            "deliverables": deliverables,
        },
        "revision_count": 0,
        "revision_summaries": [],
        "artifact_ids": [],
        "errors": [],
        "node_events": [],
        "status": "running",
        "prompt_version": PROMPT_VERSION,
        "model_metadata": {
            "llm_provider": settings.llm_provider,
            "embedding_provider": settings.embedding_provider,
            "mock": settings.llm_mock,
        },
    }
