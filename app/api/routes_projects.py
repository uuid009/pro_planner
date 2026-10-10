from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.db.models import Project
from app.db.session import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_type: str = Field(default="general", min_length=1, max_length=100)
    objective: str = Field(min_length=1)
    background: str = ""
    constraints: str = ""
    plan_start_date: date | None = None
    plan_end_date: date | None = None

    @model_validator(mode="after")
    def dates_in_order(self) -> "ProjectCreate":
        if (
            self.plan_start_date
            and self.plan_end_date
            and self.plan_start_date > self.plan_end_date
        ):
            raise ValueError("计划开始日期不能晚于结束日期")
        return self


class ProjectOut(BaseModel):
    id: UUID
    name: str
    project_type: str
    objective: str
    background: str
    constraints: str
    plan_start_date: date | None
    plan_end_date: date | None
    status: str

    model_config = {"from_attributes": True}


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project_not_found", "项目不存在")
    return project
