"""计划书生成入口。业务字段只有标题和大致内容。"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.services.workflow_service import start_proposal

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class ProposalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_brief: str = Field(min_length=1)


class ProposalCreated(BaseModel):
    project_id: UUID
    run_id: UUID
    thread_id: str
    status: str
    title: str
    model_name: str | None
    prompt_version: str | None
    mock_mode: bool


@router.post("", response_model=ProposalCreated, status_code=201)
def create_proposal(
    payload: ProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project, run = start_proposal(db, payload.title, payload.content_brief, user)
    settings = get_settings()
    return ProposalCreated(
        project_id=project.id,
        run_id=run.id,
        thread_id=run.thread_id,
        status=run.status,
        title=project.name,
        model_name=run.model_name,
        prompt_version=run.prompt_version,
        mock_mode=settings.mock_mode,
    )
