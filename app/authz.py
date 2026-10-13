"""部门与资料库范围。用户只能访问本部门和公共资料库。"""

from __future__ import annotations

DEPARTMENT_LABELS = {
    "algorithm": "算法组",
    "framework": "框架组",
    "testing": "测试组",
}
PUBLIC_LIBRARY = "public"
LIBRARY_LABELS = {**DEPARTMENT_LABELS, PUBLIC_LIBRARY: "公共资料库"}
DEPARTMENTS = tuple(DEPARTMENT_LABELS)


def visible_libraries(department: str) -> list[str]:
    return [department, PUBLIC_LIBRARY]


def resolve_upload_library(department: str, requested: str | None) -> str:
    from app.api.errors import AppError

    choice = (requested or "department").strip() or "department"
    if choice == "department":
        return department
    if choice in {PUBLIC_LIBRARY, department}:
        return choice
    raise AppError(403, "library_forbidden", "只能上传到本部门或公共资料库")


def can_read_library(department: str, library: str) -> bool:
    return library in visible_libraries(department)
