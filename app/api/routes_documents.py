from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.errors import AppError
from app.authz import can_read_library, resolve_upload_library
from app.config import get_settings
from app.db.models import Document, DocumentChunk, User
from app.db.session import get_db
from app.rag.service import index_document, index_status_for, latest_version
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
    library: str
    version_number: int
    validity_status: str
    chunk_count: int = 0
    index_status: str = "pending"
    duplicate: bool = False

    model_config = {"from_attributes": True}


class IndexOut(BaseModel):
    document_id: UUID
    version_id: UUID
    version_number: int
    chunk_count: int
    index_status: str
    embedding_provider: str
    embedding_mock: bool


def _to_out(
    document: Document,
    chunk_count: int = 0,
    duplicate: bool = False,
) -> DocumentOut:
    version = latest_version(document)
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        document_type=document.document_type,
        sha256=document.sha256,
        relative_path=document.relative_path,
        project_id=document.project_id,
        created_by=document.created_by,
        library=document.library,
        version_number=version.version_number,
        validity_status=version.validity_status,
        chunk_count=chunk_count,
        index_status=index_status_for(chunk_count),
        duplicate=duplicate,
    )


def _chunk_counts(db: Session, version_ids: list[UUID]) -> dict[UUID, int]:
    if not version_ids:
        return {}
    rows = db.execute(
        select(DocumentChunk.document_version_id, func.count())
        .where(DocumentChunk.document_version_id.in_(version_ids))
        .group_by(DocumentChunk.document_version_id)
    ).all()
    return {version_id: int(count) for version_id, count in rows}


def _load_document(db: Session, document_id: UUID, user: User) -> Document:
    loaded = db.scalar(
        select(Document).options(selectinload(Document.versions)).where(Document.id == document_id)
    )
    if loaded is None or not can_read_library(user.department, loaded.library):
        raise AppError(404, "document_not_found", "文档不存在")
    return loaded


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    library: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    target_library = resolve_upload_library(user.department, library)
    document, duplicate = register_upload(
        db,
        settings,
        filename=file.filename or "",
        content=content,
        project_id=project_id,
        created_by=user.username,
        library=target_library,
    )
    if duplicate:
        if can_read_library(user.department, document.library):
            raise AppError(
                409,
                "duplicate_document",
                "相同内容的文件已存在，未重复入库",
                {"document_id": str(document.id)},
            )
        raise AppError(403, "library_forbidden", "相同内容已在其他部门的资料库中，不能上传到别的部门")
    loaded = _load_document(db, document.id, user)
    return _to_out(loaded, chunk_count=0)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    project_id: UUID | None = None,
    document_type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(Document)
        .options(selectinload(Document.versions))
        .where(Document.library.in_([user.department, "public"]))
        .order_by(Document.uploaded_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    if document_type is not None:
        stmt = stmt.where(Document.document_type == document_type)
    documents = list(db.scalars(stmt))
    version_ids = [latest_version(document).id for document in documents]
    counts = _chunk_counts(db, version_ids)
    return [
        _to_out(document, chunk_count=counts.get(latest_version(document).id, 0))
        for document in documents
    ]


@router.post("/{document_id}/index", response_model=IndexOut)
def index_uploaded_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _load_document(db, document_id, user)
    return index_document(db, get_settings(), document_id)
