"""规则检查优先。模型意见只作为补充，不能证明事实为真。"""

from __future__ import annotations

from app.agents.proposal_agent import REQUIRED_HEADINGS
from app.config import Settings
from app.graph.json_output import complete_model, schema_hint
from app.planning.constraints import parse_iso_date, validate_plan_tasks
from app.planning.schemas import AuditIssue, AuditReport, PlanTask


def validate_plan(state: dict) -> dict:
    brief = state.get("project_brief") or {}
    tasks = [_load_task(item) for item in state.get("plan_tasks") or []]
    date_errors = [item for item in tasks if isinstance(item, AuditIssue)]
    parsed = [item for item in tasks if isinstance(item, PlanTask)]
    try:
        project_start = parse_iso_date(brief.get("plan_start_date"))
        project_end = parse_iso_date(brief.get("plan_end_date"))
    except ValueError as exc:
        date_errors.append(
            AuditIssue(
                issue_id="project-date",
                severity="error",
                location="project_brief",
                description=str(exc),
                suggestion="修正项目计划日期",
                source="rule",
            )
        )
        project_start = None
        project_end = None
    issues = date_errors + validate_plan_tasks(
        parsed, project_start=project_start, project_end=project_end
    )
    return {
        "plan_validation": [issue.model_dump(mode="json") for issue in issues],
        "status": "plan_validated",
    }


def audit_output(state: dict, settings: Settings) -> dict:
    issues = [AuditIssue.model_validate(item) for item in state.get("plan_validation") or []]
    issues.extend(_proposal_issues(state.get("proposal_draft") or {}))
    if not settings.llm_mock:
        try:
            extra = complete_model(
                settings,
                [
                    {
                        "role": "system",
                        "content": (
                            "你是审核员。只输出 AuditReport JSON。"
                            "你的意见不是真实性证明。硬性日期和依赖问题已由规则引擎给出，不要删除它们。"
                            f"结构：{schema_hint(AuditReport)}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"项目书：{state.get('proposal_draft')}\n"
                            f"任务：{state.get('plan_tasks')}\n"
                            f"规则问题：{[issue.model_dump(mode='json') for issue in issues]}"
                        ),
                    },
                ],
                AuditReport,
            )
            for issue in extra.issues:
                issue.source = "llm"
                if issue.severity == "error":
                    issue.severity = "warning"
                issues.append(issue)
        except ValueError as exc:
            issues.append(
                AuditIssue(
                    issue_id="llm-audit-unparsed",
                    severity="warning",
                    location="audit",
                    description=f"模型审核结果无法解析：{exc}",
                    suggestion="以规则检查结果为准，并由人工复核",
                    source="llm",
                )
            )
    hard_failures = [issue for issue in issues if issue.severity == "error" and issue.source == "rule"]
    passed = not hard_failures
    limited = int(state.get("revision_count") or 0) >= settings.max_revision_rounds and not passed
    report = AuditReport(issues=issues, passed=passed, mock=settings.llm_mock)
    status = "audit_passed" if passed else ("needs_human" if limited else "audit_failed")
    return {"audit_report": report.model_dump(mode="json"), "status": status}


def _proposal_issues(draft: dict) -> list[AuditIssue]:
    headings = {section.get("heading") for section in draft.get("sections") or []}
    issues: list[AuditIssue] = []
    for heading in REQUIRED_HEADINGS:
        if heading not in headings:
            issues.append(
                AuditIssue(
                    issue_id=f"missing-section-{heading}",
                    severity="error",
                    location=f"proposal.{heading}",
                    description=f"缺少章节：{heading}",
                    suggestion="补上该章节，没有证据时标记待确认",
                    source="rule",
                )
            )
    return issues


def _load_task(payload: dict) -> PlanTask | AuditIssue:
    try:
        data = dict(payload)
        data["start_date"] = parse_iso_date(data.get("start_date"))
        data["end_date"] = parse_iso_date(data.get("end_date"))
        return PlanTask.model_validate(data)
    except ValueError as exc:
        return AuditIssue(
            issue_id=f"{payload.get('task_id', 'task')}-bad-date",
            severity="error",
            location=f"tasks.{payload.get('task_id', '?')}",
            description=str(exc),
            suggestion="使用 YYYY-MM-DD，不要把无法解析的文本写成日期",
            source="rule",
        )
