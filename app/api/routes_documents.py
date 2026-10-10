from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.errors import AppError
from app.config import get_settings
from app.db.models import Document
from app.db.session import get_db
from app.services.document_service import register_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    document_type: str
    sha256: str
    relative_path: str
    project_id: UUID | None
    created_by: str
    version_number: int
    validity_status: str
    duplicate: bool = False

    model_config = {"from_attributes": True}


def _to_out(document: Document, duplicate: bool = False) -> DocumentOut:
    version = max(document.versions, key=lambda item: item.version_number)
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        document_type=document.document_type,
        sha256=document.sha256,
        relative_path=document.relative_path,
        project_id=document.project_id,
        created_by=document.created_by,
        version_number=version.version_number,
        validity_status=version.validity_status,
        duplicate=duplicate,
    )


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    document, duplicate = register_upload(
        db,
        settings,
        filename=file.filename or "",
        content=content,
        project_id=project_id,
    )
    if duplicate:
        raise AppError(
            409,
            "duplicate_document",
            "相同内容的文件已存在，未重复入库",
            {"document_id": str(document.id)},
        )
    db.refresh(document)
    document.versions  # loaded by refresh? relationship may be expired
    loaded = db.scalar(
        select(Document).options(selectinload(Document.versions)).where(Document.id == document.id)
    )
    assert loaded is not None
    return _to_out(loaded)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    project_id: UUID | None = None,
    document_type: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Document).options(selectinload(Document.versions)).order_by(Document.uploaded_at.desc())
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    if document_type is not None:
        stmt = stmt.where(Document.document_type == document_type)
    return [_to_out(document) for document in db.scalars(stmt)]
