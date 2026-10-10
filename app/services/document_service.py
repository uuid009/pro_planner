"""上传登记。解析和向量索引在后续阶段执行。"""

import hashlib
import logging
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import Settings
from app.db.models import Document, DocumentVersion, Project

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
}


def safe_storage_path(upload_dir: str, storage_name: str) -> Path:
    root = Path(upload_dir).resolve()
    target = (root / storage_name).resolve()
    if not target.is_relative_to(root):
        raise AppError(400, "invalid_path", "文件路径不合法")
    return target


def detect_document_type(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    document_type = ALLOWED_EXTENSIONS.get(suffix)
    if document_type is None:
        raise AppError(400, "unsupported_type", "只允许上传 PDF、DOCX、XLSX")
    if document_type == "pdf":
        if not content.startswith(b"%PDF"):
            raise AppError(400, "invalid_file", "文件内容与 PDF 扩展名不一致")
        return document_type
    if not content.startswith(b"PK"):
        raise AppError(400, "invalid_file", "文件内容与 Office 扩展名不一致")
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise AppError(400, "invalid_file", "Office 文件无法打开") from exc
    if "[Content_Types].xml" not in names:
        raise AppError(400, "invalid_file", "不是有效的 Office Open XML 文件")
    if document_type == "docx" and not any(name.startswith("word/") for name in names):
        raise AppError(400, "invalid_file", "文件内容与 DOCX 扩展名不一致")
    if document_type == "xlsx" and not any(name.startswith("xl/") for name in names):
        raise AppError(400, "invalid_file", "文件内容与 XLSX 扩展名不一致")
    return document_type


def register_upload(
    db: Session,
    settings: Settings,
    *,
    filename: str,
    content: bytes,
    project_id: UUID | None,
) -> tuple[Document, bool]:
    original_name = Path(filename).name
    if not original_name or original_name in {".", ".."}:
        raise AppError(400, "invalid_filename", "文件名不合法")
    if len(content) == 0:
        raise AppError(400, "empty_file", "不能上传空文件")
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, "file_too_large", "文件超过大小限制")
    document_type = detect_document_type(original_name, content)
    if project_id is not None and db.get(Project, project_id) is None:
        raise AppError(404, "project_not_found", "项目不存在")

    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing is not None:
        logger.info("duplicate_upload sha256=%s document_id=%s", digest, existing.id)
        return existing, True

    storage_name = f"{uuid4().hex}{Path(original_name).suffix.lower()}"
    target = safe_storage_path(settings.upload_dir, storage_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    relative_path = storage_name

    document = Document(
        filename=original_name,
        document_type=document_type,
        sha256=digest,
        relative_path=relative_path,
        project_id=project_id,
        created_by=settings.demo_user_id,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentVersion(
            document_id=document.id,
            version_number=1,
            sha256=digest,
            validity_status="active",
            relative_path=relative_path,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        target.unlink(missing_ok=True)
        existing = db.scalar(select(Document).where(Document.sha256 == digest))
        if existing is not None:
            return existing, True
        raise
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(document)
    logger.info(
        "document_registered document_id=%s type=%s bytes=%s",
        document.id,
        document_type,
        len(content),
    )
    return document, False
