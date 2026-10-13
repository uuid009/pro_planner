from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import get_settings
from app.db.models import Project
from app.db.session import get_db
from app.services.artifact_service import compare_artifacts, get_artifact, list_evidence, list_project_artifacts
from app.services.document_service import safe_storage_path
from app.services.workflow_service import (
    fork_run,
    get_run,
    list_checkpoints,
    list_events,
    list_project_runs,
    resume_run,
    review_snapshot,
    start_run,
)

router = APIRouter(tags=["workflows"])


class RunCreate(BaseModel):
    user_request: str = Field(min_length=1)
    deliverables: list[str] = Field(default_factory=list)


class ResumeIn(BaseModel):
    decision: Literal["approve", "revise", "request_information", "select_option"] | None = None
    comment: str = ""
    information: str = ""
    selected_option: str | None = None


class ForkIn(BaseModel):
    checkpoint_id: str = Field(min_length=1)
    branch_label: str = ""
    user_request: str | None = None
    constraints: str | None = None


class RunOut(BaseModel):
    id: UUID
    project_id: UUID
    thread_id: str
    parent_run_id: UUID | None = None
    parent_checkpoint_id: str | None = None
    branch_label: str | None = None
    status: str
    model_name: str | None
    prompt_version: str | None
    error_summary: str | None = None

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id: UUID
    node_name: str
    event_type: str
    status: str
    duration_ms: int | None
    error_summary: str | None = None

    model_config = {"from_attributes": True}


class CheckpointOut(BaseModel):
    checkpoint_id: str
    next_nodes: list[str]
    status: str | None = None
    revision_count: int
    task_count: int
    step: int | None = None
    created_at: str | None = None


class ArtifactOut(BaseModel):
    id: UUID
    project_id: UUID
    run_id: UUID | None
    artifact_type: str
    version_number: int
    parent_version_id: UUID | None = None
    sha256: str
    summary: str
    review_status: str

    model_config = {"from_attributes": True}


_DOWNLOADS = {
    "draft_snapshot": ("application/json", ".json"),
    "proposal_docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "plan_xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}


class EvidenceOut(BaseModel):
    id: UUID
    field_path: str
    chunk_id: UUID | None
    quote: str
    verification_status: str
    verification_note: str

    model_config = {"from_attributes": True}


@router.post("/api/projects/{project_id}/runs", response_model=RunOut, status_code=201)
def create_run(project_id: UUID, payload: RunCreate, db: Session = Depends(get_db)):
    return start_run(db, project_id, payload.user_request, payload.deliverables)


@router.get("/api/runs/{run_id}", response_model=RunOut)
def read_run(run_id: UUID, db: Session = Depends(get_db)):
    return get_run(db, run_id)


@router.get("/api/runs/{run_id}/events", response_model=list[EventOut])
def read_events(run_id: UUID, db: Session = Depends(get_db)):
    return list_events(db, run_id)


@router.get("/api/runs/{run_id}/checkpoints", response_model=list[CheckpointOut])
def read_checkpoints(run_id: UUID, db: Session = Depends(get_db)):
    return list_checkpoints(db, run_id)


@router.get("/api/runs/{run_id}/review")
def read_review(run_id: UUID, db: Session = Depends(get_db)):
    return review_snapshot(db, run_id)


@router.post("/api/runs/{run_id}/resume", response_model=RunOut)
def resume(run_id: UUID, payload: ResumeIn, db: Session = Depends(get_db)):
    return resume_run(db, run_id, payload.model_dump())


@router.post("/api/runs/{run_id}/fork", response_model=RunOut, status_code=201)
def fork(run_id: UUID, payload: ForkIn, db: Session = Depends(get_db)):
    return fork_run(
        db,
        run_id,
        checkpoint_id=payload.checkpoint_id,
        branch_label=payload.branch_label,
        user_request=payload.user_request,
        constraints=payload.constraints,
    )


@router.get("/api/projects/{project_id}/runs", response_model=list[RunOut])
def read_project_runs(project_id: UUID, db: Session = Depends(get_db)):
    return list_project_runs(db, project_id)


@router.get("/api/projects/{project_id}/artifacts", response_model=list[ArtifactOut])
def read_artifacts(project_id: UUID, db: Session = Depends(get_db)):
    if db.get(Project, project_id) is None:
        raise AppError(404, "project_not_found", "项目不存在")
    return list_project_artifacts(db, project_id)


@router.get("/api/artifacts/{artifact_id}/evidence", response_model=list[EvidenceOut])
def read_artifact_evidence(artifact_id: UUID, db: Session = Depends(get_db)):
    return list_evidence(db, artifact_id)


@router.get("/api/artifacts/compare")
def compare(left: UUID, right: UUID, db: Session = Depends(get_db)):
    return compare_artifacts(db, get_settings(), left, right)


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    artifact = get_artifact(db, artifact_id)
    path = safe_storage_path(get_settings().artifact_dir, artifact.relative_path)
    if not path.is_file():
        raise AppError(404, "artifact_file_missing", "产物文件不存在")
    media_type, suffix = _DOWNLOADS.get(artifact.artifact_type, ("application/octet-stream", ""))
    filename = f"{artifact.artifact_type}_v{artifact.version_number}{suffix}"
    return FileResponse(path, media_type=media_type, filename=filename)
