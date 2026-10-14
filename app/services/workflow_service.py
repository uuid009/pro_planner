"""创建、恢复和分叉工作流。分叉使用新的 thread_id，不改写父运行的产物和审批。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.authz import PUBLIC_LIBRARY, visible_libraries
from app.config import get_settings
from app.db.models import AgentEvent, ApprovalRecord, Project, User, WorkflowRun
from app.graph.runtime import bind_db, persist_node_events, unbind_db
from app.graph.state import PROMPT_VERSION
from app.graph.workflow import get_compiled_graph
from app.services.artifact_service import persist_approved_exports


def start_proposal(
    db: Session,
    title: str,
    content_brief: str,
    user: User | None = None,
) -> tuple[Project, WorkflowRun]:
    """用标题和大致内容创建一次计划书生成。组范围来自当前用户，不从请求里读取。"""
    project = Project(
        name=title.strip(),
        project_type="proposal",
        objective=content_brief.strip(),
        background=content_brief.strip(),
        constraints="",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    run = start_run(db, project.id, content_brief.strip(), [], user)
    return project, run


def start_run(
    db: Session,
    project_id: UUID,
    user_request: str,
    deliverables: list[str],
    user: User | None = None,
) -> WorkflowRun:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project_not_found", "项目不存在")
    settings = get_settings()
    run = WorkflowRun(
        id=uuid4(),
        project_id=project.id,
        thread_id=secrets.token_hex(16),
        owner_username=user.username if user else None,
        owner_department=user.department if user else None,
        status="running",
        model_name="mock" if settings.llm_mock else settings.llm_model,
        prompt_version=PROMPT_VERSION,
        started_at=datetime.now(UTC),
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
        graph.invoke(
            _initial_state(
                run,
                project,
                user_request,
                deliverables,
                settings,
                visible_libraries(user.department) if user else [PUBLIC_LIBRARY],
            ),
            config,
        )
    except Exception as exc:
        run.status = "failed"
        run.error_summary = type(exc).__name__
        run.finished_at = datetime.now(UTC)
        db.commit()
        raise AppError(
            500, "workflow_failed", "工作流执行失败", {"error": type(exc).__name__}
        ) from exc
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    _persist_new_events(db, run.id, (snapshot.values or {}).get("node_events") or [])
    run.status = status_from_snapshot(snapshot)
    if run.status == "failed":
        errors = (snapshot.values or {}).get("errors") or []
        run.error_summary = "; ".join(errors)[:500] or "failed"
        run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: UUID, user: User | None = None) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None or not _can_read_run(run, user):
        raise AppError(404, "run_not_found", "工作流运行不存在")
    return run


def list_project_runs(db: Session, project_id: UUID, user: User | None = None) -> list[WorkflowRun]:
    if db.get(Project, project_id) is None:
        raise AppError(404, "project_not_found", "项目不存在")
    stmt = select(WorkflowRun).where(WorkflowRun.project_id == project_id)
    if user is None:
        stmt = stmt.where(WorkflowRun.owner_department.is_(None))
    else:
        stmt = stmt.where(
            (WorkflowRun.owner_department.is_(None))
            | (WorkflowRun.owner_department == user.department)
        )
    return list(db.scalars(stmt.order_by(WorkflowRun.created_at.desc())))


def list_events(db: Session, run_id: UUID, user: User | None = None) -> list[AgentEvent]:
    get_run(db, run_id, user)
    return list(
        db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.created_at.asc())
        )
    )


def resume_run(db: Session, run_id: UUID, decision: dict, user: User | None = None) -> WorkflowRun:
    run = get_run(db, run_id, user)
    graph = _graph_or_503()
    config = {"configurable": {"thread_id": run.thread_id}}
    snapshot = graph.get_state(config)
    pending = set(snapshot.next or ())
    if not pending:
        raise AppError(409, "run_not_waiting", "该运行没有停在人工节点，不能恢复")
    payload = _resume_payload(pending, decision)
    approval = None
    if "human_approval" in pending:
        approval = ApprovalRecord(
            run_id=run.id,
            demo_user_id=get_settings().demo_user_id,
            decision=str(payload.get("decision") or ""),
            comment=str(payload.get("comment") or payload.get("information") or ""),
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
    _invoke(db, graph, Command(resume=payload), config, run)
    snapshot = graph.get_state(config)
    if (
        approval is not None
        and payload.get("decision") == "approve"
        and status_from_snapshot(snapshot) == "approved_pending_export"
    ):
        artifact = persist_approved_exports(
            db,
            get_settings(),
            project_id=run.project_id,
            run_id=run.id,
            proposal=(snapshot.values or {}).get("proposal_draft") or {},
            tasks=(snapshot.values or {}).get("plan_tasks") or [],
            evidence_items=((snapshot.values or {}).get("evidence_bundle") or {}).get("items")
            or [],
            prompt_version=run.prompt_version,
        )
        approval.artifact_version_id = artifact.id
        db.commit()
    db.refresh(run)
    return run


def list_checkpoints(db: Session, run_id: UUID, user: User | None = None) -> list[dict]:
    run = get_run(db, run_id, user)
    graph = _graph_or_503()
    config = {"configurable": {"thread_id": run.thread_id}}
    rows = []
    for snapshot in graph.get_state_history(config, limit=50):
        configurable = (snapshot.config or {}).get("configurable") or {}
        checkpoint_id = configurable.get("checkpoint_id")
        if not checkpoint_id:
            continue
        values = snapshot.values or {}
        metadata = snapshot.metadata or {}
        rows.append(
            {
                "checkpoint_id": checkpoint_id,
                "next_nodes": list(snapshot.next or ()),
                "status": values.get("status"),
                "revision_count": int(values.get("revision_count") or 0),
                "task_count": len(values.get("plan_tasks") or []),
                "step": metadata.get("step"),
                "created_at": snapshot.created_at,
            }
        )
    return rows


def fork_run(
    db: Session,
    run_id: UUID,
    *,
    checkpoint_id: str,
    branch_label: str,
    user_request: str | None,
    constraints: str | None,
    user: User | None = None,
) -> WorkflowRun:
    parent = get_run(db, run_id, user)
    graph = _graph_or_503()
    source = graph.get_state(
        {"configurable": {"thread_id": parent.thread_id, "checkpoint_id": checkpoint_id}}
    )
    if not source.values:
        raise AppError(404, "checkpoint_not_found", "检查点不存在")
    child = WorkflowRun(
        id=uuid4(),
        project_id=parent.project_id,
        thread_id=secrets.token_hex(16),
        parent_run_id=parent.id,
        parent_checkpoint_id=checkpoint_id,
        branch_label=branch_label or None,
        owner_username=user.username if user else parent.owner_username,
        owner_department=user.department if user else parent.owner_department,
        status="running",
        model_name=parent.model_name,
        prompt_version=parent.prompt_version,
        started_at=datetime.now(UTC),
    )
    db.add(child)
    db.commit()
    seed = _seed_from_checkpoint(
        source.values, child, parent, checkpoint_id, user_request, constraints, user
    )
    as_node = _fork_source(tuple(source.next or ()))
    child_config = {"configurable": {"thread_id": child.thread_id}}
    if as_node is None:
        # 已结束的检查点只复制状态。用终态节点写入，避免在新线程上再次执行。
        graph.update_state(child_config, seed, as_node="fail")
        child.status = status_from_snapshot(graph.get_state(child_config))
        db.commit()
        db.refresh(child)
        return child
    graph.update_state(child_config, seed, as_node=as_node)
    _invoke(db, graph, None, child_config, child)
    db.refresh(child)
    return child


def review_snapshot(db: Session, run_id: UUID, user: User | None = None) -> dict:
    run = get_run(db, run_id, user)
    graph = _graph_or_503()
    snapshot = graph.get_state({"configurable": {"thread_id": run.thread_id}})
    values = snapshot.values or {}
    proposal = values.get("proposal_draft") or {}
    tasks = values.get("plan_tasks") or []
    issues = ((values.get("audit_report") or {}).get("issues")) or []
    evidence = ((values.get("evidence_bundle") or {}).get("items")) or []
    approvals = list(
        db.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.run_id == run.id)
            .order_by(ApprovalRecord.created_at.asc())
        )
    )
    return {
        "run_id": run.id,
        "thread_id": run.thread_id,
        "status": run.status,
        "prompt_version": run.prompt_version,
        "demo_user_id": get_settings().demo_user_id,
        "demo_identity_notice": "当前审核人是本地演示用户，不是生产身份认证。",
        "proposal_title": proposal.get("title"),
        "sections": [
            {
                "heading": section.get("heading"),
                "body": section.get("body") or "",
                "needs_confirmation": section.get("needs_confirmation"),
                "evidence_ids": section.get("evidence_ids") or [],
            }
            for section in proposal.get("sections") or []
        ],
        "tasks": [
            {
                "task_id": task.get("task_id"),
                "title": task.get("title"),
                "owner_role": task.get("owner_role"),
                "description": task.get("description"),
                "start_date": task.get("start_date"),
                "end_date": task.get("end_date"),
                "deliverables": task.get("deliverables"),
                "needs_confirmation": task.get("needs_confirmation"),
            }
            for task in tasks
        ],
        "issues": [
            {
                "issue_id": issue.get("issue_id"),
                "severity": issue.get("severity"),
                "location": issue.get("location"),
                "description": issue.get("description"),
            }
            for issue in issues
        ],
        "evidence": [
            {
                "evidence_id": item.get("evidence_id"),
                "title": item.get("title"),
                "page_number": item.get("page_number"),
                "section": item.get("section"),
                "quote": item.get("quote") or "",
                "verification_status": item.get("verification_status"),
            }
            for item in evidence
        ],
        "approvals": [
            {
                "id": item.id,
                "decision": item.decision,
                "comment": item.comment,
                "demo_user_id": item.demo_user_id,
                "artifact_version_id": item.artifact_version_id,
            }
            for item in approvals
        ],
        "unresolved_items": [
            section.get("heading")
            for section in proposal.get("sections") or []
            if section.get("needs_confirmation")
        ],
        "evidence_gaps": ((values.get("evidence_bundle") or {}).get("gaps")) or [],
    }


def status_from_snapshot(snapshot) -> str:
    pending = set(snapshot.next or ())
    if "human_approval" in pending:
        return "awaiting_review"
    if "human_clarification" in pending:
        return "awaiting_information"
    values = snapshot.values or {}
    return str(values.get("status") or "unknown")


def _can_read_run(run: WorkflowRun, user: User | None) -> bool:
    if not run.owner_department:
        return True
    return user is not None and user.department == run.owner_department


def _initial_state(
    run: WorkflowRun,
    project: Project,
    user_request: str,
    deliverables: list[str],
    settings,
    libraries: list[str],
) -> dict:
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
            "plan_start_date": project.plan_start_date.isoformat()
            if project.plan_start_date
            else None,
            "plan_end_date": project.plan_end_date.isoformat() if project.plan_end_date else None,
            "deliverables": deliverables,
        },
        "revision_count": 0,
        "revision_summaries": [],
        "artifact_ids": [],
        "errors": [],
        "node_events": [],
        "status": "running",
        "visible_libraries": libraries,
        "prompt_version": PROMPT_VERSION,
        "model_metadata": {
            "llm_provider": settings.llm_provider,
            "embedding_provider": settings.embedding_provider,
            "mock": settings.llm_mock,
        },
    }


def _graph_or_503():
    try:
        return get_compiled_graph()
    except RuntimeError as exc:
        raise AppError(503, "checkpointer_unavailable", "工作流检查点存储不可用") from exc


def _invoke(db: Session, graph, payload, config: dict, run: WorkflowRun) -> None:
    bind_db(db)
    try:
        graph.invoke(payload, config)
    except GraphInterrupt:
        pass
    except Exception as exc:
        run.status = "failed"
        run.error_summary = type(exc).__name__
        run.finished_at = datetime.now(UTC)
        db.commit()
        raise AppError(
            500, "workflow_failed", "工作流执行失败", {"error": type(exc).__name__}
        ) from exc
    finally:
        unbind_db()
    snapshot = graph.get_state(config)
    _persist_new_events(db, run.id, (snapshot.values or {}).get("node_events") or [])
    run.status = status_from_snapshot(snapshot)
    if run.status in {"approved_pending_export", "option_selected", "failed"}:
        run.finished_at = datetime.now(UTC)
    if run.status == "failed":
        errors = (snapshot.values or {}).get("errors") or []
        run.error_summary = "; ".join(errors)[:500] or "failed"
    db.commit()


def _persist_new_events(db: Session, run_id: UUID, events: list[dict]) -> None:
    existing = int(
        db.scalar(select(func.count()).select_from(AgentEvent).where(AgentEvent.run_id == run_id))
        or 0
    )
    persist_node_events(db, run_id, events[existing:])


def _resume_payload(pending: set[str], decision: dict) -> dict:
    if "human_clarification" in pending:
        text = str(decision.get("information") or decision.get("comment") or "").strip()
        if not text:
            raise AppError(422, "information_required", "补充信息不能为空")
        return {"information": text, "comment": text}
    kind = str(decision.get("decision") or "")
    if kind not in {"approve", "revise", "request_information", "select_option"}:
        raise AppError(
            422,
            "invalid_decision",
            "决策必须是 approve、revise、request_information 或 select_option",
        )
    if kind == "revise" and not str(decision.get("comment") or "").strip():
        raise AppError(422, "comment_required", "退回修订时必须填写意见")
    if (
        kind == "request_information"
        and not str(decision.get("information") or decision.get("comment") or "").strip()
    ):
        raise AppError(422, "information_required", "请求补充信息时必须填写内容")
    if kind == "select_option" and not str(decision.get("selected_option") or "").strip():
        raise AppError(422, "option_required", "选择方案时必须提供选项")
    if "human_approval" not in pending:
        raise AppError(409, "run_not_waiting", "当前暂停点不接受审批决策")
    return {
        "decision": kind,
        "comment": str(decision.get("comment") or ""),
        "information": str(decision.get("information") or ""),
        "selected_option": decision.get("selected_option"),
    }


def _seed_from_checkpoint(
    values: dict,
    child: WorkflowRun,
    parent: WorkflowRun,
    checkpoint_id: str,
    user_request: str | None,
    constraints: str | None,
    user: User | None,
) -> dict:
    seed = {
        key: value
        for key, value in values.items()
        if key not in {"errors", "node_events", "artifact_ids", "revision_summaries"}
    }
    seed["run_id"] = str(child.id)
    seed["thread_id"] = child.thread_id
    if user_request:
        seed["user_request"] = user_request.strip()
    if constraints:
        brief = dict(seed.get("project_brief") or {})
        brief["constraints"] = constraints
        seed["project_brief"] = brief
        snapshot = dict(seed.get("project_snapshot") or {})
        snapshot["constraints"] = constraints
        seed["project_snapshot"] = snapshot
    metadata = dict(seed.get("model_metadata") or {})
    metadata["parent_run_id"] = str(parent.id)
    metadata["forked_from_checkpoint"] = checkpoint_id
    seed["model_metadata"] = metadata
    seed["visible_libraries"] = visible_libraries(user.department) if user else [PUBLIC_LIBRARY]
    return seed


def _fork_source(next_nodes: tuple[str, ...]) -> str | None:
    pending = set(next_nodes)
    if not pending:
        return None
    if pending <= {"generate_proposal", "generate_plan"}:
        return "assess_evidence"
    if len(pending) != 1:
        raise AppError(409, "fork_unsupported", "该检查点有多个后续节点，暂不能分叉")
    source = {
        "human_approval": "audit_output",
        "human_clarification": "check_missing_information",
        "revise_output": "audit_output",
        "retrieve_evidence": "check_missing_information",
        "assess_evidence": "retrieve_evidence",
        "validate_plan": "generate_plan",
        "audit_output": "validate_plan",
        "check_missing_information": "analyze_request",
    }.get(next(iter(pending)))
    if source is None:
        raise AppError(409, "fork_unsupported", "该检查点位置暂不能分叉")
    return source
