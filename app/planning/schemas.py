"""项目书、任务计划与审核的结构化输出。"""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.rag.schemas import EvidenceItem


class ProjectBrief(BaseModel):
    title: str
    objective: str
    background: str = ""
    constraints: str = ""
    deliverables: list[str] = Field(default_factory=list)
    plan_start_date: date | None = None
    plan_end_date: date | None = None
    project_type: str = "general"
    supplement: str = ""


class ProposalSection(BaseModel):
    heading: str
    body: str
    evidence_ids: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class ProposalDocument(BaseModel):
    title: str
    sections: list[ProposalSection]
    mock: bool = False


class PlanTask(BaseModel):
    task_id: str
    title: str
    description: str = ""
    owner_role: str
    start_date: date | None = None
    end_date: date | None = None
    dependency_ids: list[str] = Field(default_factory=list)
    deliverables: str = ""
    acceptance_criteria: str = ""
    risk_notes: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class PlanDocument(BaseModel):
    tasks: list[PlanTask]
    mock: bool = False


class AuditIssue(BaseModel):
    issue_id: str
    severity: Literal["error", "warning", "info"]
    location: str
    description: str
    evidence: str = ""
    suggestion: str = ""
    source: Literal["rule", "llm"] = "rule"


class AuditReport(BaseModel):
    issues: list[AuditIssue]
    passed: bool
    mock: bool = False


class ReviewDecision(BaseModel):
    decision: Literal["approve", "revise", "request_information", "select_option"]
    comment: str = ""
    selected_option: str | None = None


class EvidenceBundle(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


__all__ = [
    "UUID",
    "AuditIssue",
    "AuditReport",
    "EvidenceBundle",
    "EvidenceItem",
    "PlanDocument",
    "PlanTask",
    "ProjectBrief",
    "ProposalDocument",
    "ProposalSection",
    "ReviewDecision",
]
