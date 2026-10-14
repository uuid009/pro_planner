from datetime import date

from app.agents.audit_agent import _load_task
from app.planning.constraints import validate_plan_tasks
from app.planning.schemas import AuditIssue, PlanTask


def _task(**overrides) -> PlanTask:
    values = {
        "task_id": "T1",
        "title": "确认范围",
        "owner_role": "策划专责",
        "start_date": date(2026, 1, 2),
        "end_date": date(2026, 1, 20),
        "deliverables": "确认单",
        "acceptance_criteria": "评审通过",
    }
    values.update(overrides)
    return PlanTask(**values)


def test_valid_plan_has_no_errors():
    issues = validate_plan_tasks(
        [_task(), _task(task_id="T2", dependency_ids=["T1"], title="实施")],
        project_start=date(2026, 1, 1),
        project_end=date(2026, 6, 30),
    )
    assert [issue for issue in issues if issue.severity == "error"] == []


def test_rejects_date_order_missing_dependency_and_cycle():
    issues = validate_plan_tasks(
        [
            _task(
                task_id="A",
                end_date=date(2026, 1, 1),
                start_date=date(2026, 2, 1),
                dependency_ids=["B"],
            ),
            _task(task_id="B", dependency_ids=["A"], title="实施"),
        ],
        project_start=date(2026, 1, 1),
        project_end=date(2026, 6, 30),
    )
    descriptions = " ".join(issue.description for issue in issues)
    assert "开始日期晚于结束日期" in descriptions
    assert "循环" in descriptions


def test_missing_acceptance_is_an_error():
    issues = validate_plan_tasks(
        [_task(deliverables="", acceptance_criteria="")],
        project_start=None,
        project_end=None,
    )
    assert any(issue.issue_id.endswith("acceptance") for issue in issues)


def test_unparseable_date_is_not_coerced():
    loaded = _load_task(
        {"task_id": "T9", "title": "里程碑", "owner_role": "策划专责", "start_date": "下周一"}
    )
    assert isinstance(loaded, AuditIssue)
    assert "无法解析日期" in loaded.description


def test_dependency_must_exist():
    issues = validate_plan_tasks(
        [_task(dependency_ids=["MISSING"])],
        project_start=None,
        project_end=None,
    )
    assert any("不存在" in issue.description for issue in issues)
