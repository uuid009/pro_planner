from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.workflow_service import get_run, list_events, start_run

router = APIRouter(tags=["workflows"])


class RunCreate(BaseModel):
    user_request: str = Field(min_length=1)
    deliverables: list[str] = Field(default_factory=list)


class RunOut(BaseModel):
    id: UUID
    project_id: UUID
    thread_id: str
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


@router.post("/api/projects/{project_id}/runs", response_model=RunOut, status_code=201)
def create_run(project_id: UUID, payload: RunCreate, db: Session = Depends(get_db)):
    return start_run(db, project_id, payload.user_request, payload.deliverables)


@router.get("/api/runs/{run_id}", response_model=RunOut)
def read_run(run_id: UUID, db: Session = Depends(get_db)):
    return get_run(db, run_id)


@router.get("/api/runs/{run_id}/events", response_model=list[EventOut])
def read_events(run_id: UUID, db: Session = Depends(get_db)):
    return list_events(db, run_id)
