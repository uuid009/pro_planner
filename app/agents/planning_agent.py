"""生成结构化任务。没有具体人员输入时只使用角色占位符。"""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.graph.json_output import complete_model, schema_hint
from app.planning.constraints import parse_iso_date
from app.planning.schemas import PlanDocument, PlanTask


def generate_plan(state: dict, settings: Settings) -> dict:
    brief = state.get("project_brief") or {}
    evidence = (state.get("evidence_bundle") or {}).get("items") or []
    if settings.llm_mock:
        document = _mock_plan(brief, evidence, state.get("user_request") or "", settings.llm_mock)
    else:
        document = complete_model(
            settings,
            [
                {
                    "role": "system",
                    "content": (
                        "你是计划编制员。只输出 PlanDocument JSON，tasks 为结构化任务列表。"
                        "owner_role 只能是角色，不能写具体人名。没有证据的任务 needs_confirmation=true。"
                        "日期使用 YYYY-MM-DD，无法确定时设为 null，不要猜测。"
                        f"结构：{schema_hint(PlanDocument)}"
                    ),
                },
                {"role": "user", "content": f"简报：{brief}\n证据条数：{len(evidence)}"},
            ],
            PlanDocument,
        )
    return {
        "plan_tasks": [task.model_dump(mode="json") for task in document.tasks],
        "model_metadata": {
            "node": "generate_plan",
            "mock": document.mock,
            "task_count": len(document.tasks),
        },
    }


def _mock_plan(brief: dict, evidence: list[dict], user_request: str, mock: bool) -> PlanDocument:
    start = parse_iso_date(brief.get("plan_start_date"))
    end = parse_iso_date(brief.get("plan_end_date"))
    evidence_ids = [
        str(item.get("evidence_id")) for item in evidence[:2] if item.get("evidence_id")
    ]
    needs_confirmation = not evidence_ids or start is None or end is None
    if start and end:
        midpoint = min(start + timedelta(days=14), end)
        second_end = start - timedelta(days=1) if "需要修订" in user_request else end
    else:
        midpoint = None
        second_end = None
    tasks = [
        PlanTask(
            task_id="T1",
            title="确认项目目标与资料",
            description=brief.get("objective") or "整理项目目标",
            owner_role="策划专责",
            start_date=start,
            end_date=midpoint,
            deliverables="项目目标确认单",
            acceptance_criteria="目标、日期和约束已书面确认",
            risk_notes="资料不足时不得补造事实",
            evidence_ids=evidence_ids,
            needs_confirmation=needs_confirmation,
        ),
        PlanTask(
            task_id="T2",
            title="编制实施方案与任务计划",
            description="依据证据编制项目书和任务表",
            owner_role="实施专责",
            start_date=midpoint,
            end_date=second_end,
            dependency_ids=["T1"],
            deliverables="、".join(brief.get("deliverables") or ["项目书草稿"]),
            acceptance_criteria="通过规则校验并提交人工审核",
            risk_notes=brief.get("constraints") or "待确认约束",
            evidence_ids=evidence_ids,
            needs_confirmation=needs_confirmation,
        ),
    ]
    return PlanDocument(tasks=tasks, mock=mock)
