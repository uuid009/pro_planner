"""按审核问题做局部修订，并保留修订摘要。"""

from __future__ import annotations

from app.config import Settings
from app.graph.json_output import complete_model, schema_hint
from app.planning.constraints import parse_iso_date
from app.planning.schemas import PlanDocument, ProposalDocument


def revise_output(state: dict, settings: Settings) -> dict:
    issues = (state.get("audit_report") or {}).get("issues") or []
    error_issues = [issue for issue in issues if issue.get("severity") == "error"]
    if settings.llm_mock:
        proposal = state.get("proposal_draft") or {}
        tasks = _fix_tasks(
            state.get("plan_tasks") or [],
            state.get("project_brief") or {},
            str(state.get("review_feedback") or ""),
        )
        summary = f"Mock 修订了 {len(error_issues)} 条规则问题"
    else:
        proposal_model = complete_model(
            settings,
            _messages("只修订项目书中被点名的章节，保留其余章节。", ProposalDocument, state),
            ProposalDocument,
        )
        plan_model = complete_model(
            settings,
            _messages("只修订被点名的任务，保留未点名任务的编号。", PlanDocument, state),
            PlanDocument,
        )
        proposal = proposal_model.model_dump(mode="json")
        tasks = [task.model_dump(mode="json") for task in plan_model.tasks]
        summary = f"按 {len(error_issues)} 条问题修订项目书和任务计划"
    return {
        "proposal_draft": proposal,
        "plan_tasks": tasks,
        "revision_count": int(state.get("revision_count") or 0) + 1,
        "revision_summaries": [summary],
        "status": "revised",
        "model_metadata": {"node": "revise_output", "mock": settings.llm_mock},
    }


def _messages(instruction: str, schema: type, state: dict) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                f"{instruction}不得编造预算、人员或新的事实。没有证据就标记 needs_confirmation。"
                f"只返回 JSON。结构：{schema_hint(schema)}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题：{(state.get('audit_report') or {}).get('issues')}\n"
                f"反馈：{state.get('review_feedback') or ''}\n"
                f"项目书：{state.get('proposal_draft')}\n任务：{state.get('plan_tasks')}"
            ),
        },
    ]


def _fix_tasks(tasks: list[dict], brief: dict, feedback: str) -> list[dict]:
    start = parse_iso_date(brief.get("plan_start_date"))
    end = parse_iso_date(brief.get("plan_end_date"))
    feedback = feedback.strip()
    fixed = []
    for raw in tasks:
        task = dict(raw)
        if feedback:
            task["description"] = f"{task.get('description') or ''}\n修订意见：{feedback[:200]}".strip()
        if start and end:
            task["start_date"] = start.isoformat()
            task["end_date"] = end.isoformat()
        if not str(task.get("deliverables") or "").strip() and not str(task.get("acceptance_criteria") or "").strip():
            task["deliverables"] = "待确认交付物"
            task["needs_confirmation"] = True
        owner = str(task.get("owner_role") or "")
        if owner and not any(marker in owner for marker in ("专责", "经理", "负责人", "工程师", "角色", "组", "岗")):
            task["owner_role"] = "实施专责"
        fixed.append(task)
    return fixed
