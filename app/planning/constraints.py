"""任务计划的确定性校验。规则结果优先于模型自评。"""

from __future__ import annotations

from datetime import date, datetime

from app.planning.schemas import AuditIssue, PlanTask


def validate_plan_tasks(
    tasks: list[PlanTask],
    *,
    project_start: date | None,
    project_end: date | None,
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    known_ids = {task.task_id for task in tasks if task.task_id}
    for task in tasks:
        location = f"tasks.{task.task_id or '?'}"
        if not task.title.strip():
            issues.append(
                _issue(f"{task.task_id}-title", location, "任务名称不能为空", "补充明确的任务名称")
            )
        if task.start_date and task.end_date and task.start_date > task.end_date:
            issues.append(
                _issue(
                    f"{task.task_id}-date-order",
                    location,
                    "开始日期晚于结束日期",
                    "调整起止日期，使开始日期不晚于结束日期",
                )
            )
        if project_start and task.start_date and task.start_date < project_start:
            issues.append(
                _issue(
                    f"{task.task_id}-before-project",
                    location,
                    "任务开始日期早于项目计划开始日期",
                    "把任务日期放进项目计划范围内",
                )
            )
        if project_end and task.end_date and task.end_date > project_end:
            issues.append(
                _issue(
                    f"{task.task_id}-after-project",
                    location,
                    "任务结束日期晚于项目计划结束日期",
                    "把任务日期放进项目计划范围内",
                )
            )
        for dependency_id in task.dependency_ids:
            if dependency_id not in known_ids:
                issues.append(
                    _issue(
                        f"{task.task_id}-missing-dep-{dependency_id}",
                        location,
                        f"依赖任务 {dependency_id} 不存在",
                        "删除该依赖或补上对应任务",
                    )
                )
            if dependency_id == task.task_id:
                issues.append(
                    _issue(
                        f"{task.task_id}-self-dep",
                        location,
                        "任务不能依赖自身",
                        "去掉对自身的依赖",
                    )
                )
        if task.title.strip() and not (
            task.deliverables.strip() or task.acceptance_criteria.strip()
        ):
            issues.append(
                _issue(
                    f"{task.task_id}-acceptance",
                    location,
                    "任务缺少交付物和验收标准",
                    "至少补充交付物或验收标准之一",
                )
            )
        if _looks_like_named_person(task.owner_role):
            issues.append(
                _issue(
                    f"{task.task_id}-owner",
                    location,
                    "负责人应使用角色占位，不能写成具体人员",
                    "改成角色，例如策划专责、实施专责",
                    severity="warning",
                )
            )
    cycle = _find_cycle(tasks)
    if cycle:
        issues.append(
            _issue(
                "dependency-cycle",
                "tasks.dependencies",
                f"依赖存在循环：{' -> '.join(cycle)}",
                "打破循环依赖后再提交",
            )
        )
    return issues


def parse_iso_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError("日期必须是 ISO 字符串")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"无法解析日期：{value}") from exc


def _issue(
    issue_id: str,
    location: str,
    description: str,
    suggestion: str,
    *,
    severity: str = "error",
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        severity=severity,  # type: ignore[arg-type]
        location=location,
        description=description,
        suggestion=suggestion,
        source="rule",
    )


def _looks_like_named_person(owner_role: str) -> bool:
    text = owner_role.strip()
    if not text:
        return False
    role_markers = ("专责", "经理", "负责人", "工程师", "角色", "组", "岗")
    return not any(marker in text for marker in role_markers)


def _find_cycle(tasks: list[PlanTask]) -> list[str] | None:
    graph = {task.task_id: list(task.dependency_ids) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def walk(node: str) -> list[str] | None:
        if node in visiting:
            if node in stack:
                return stack[stack.index(node) :] + [node]
            return [node, node]
        if node in visited or node not in graph:
            return None
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            cycle = walk(nxt)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in graph:
        cycle = walk(node)
        if cycle:
            return cycle
    return None
