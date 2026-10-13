from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk, DocumentVersion
from app.rag.lexical_search import common_document_filters


def vector_search(
    db: Session,
    query_vector: list[float],
    *,
    limit: int,
    project_id: UUID | None = None,
    document_type: str | None = None,
    document_ids: list[UUID] | None = None,
    validity_status: str = "active",
) -> list[tuple[DocumentChunk, float]]:
    filters = common_document_filters(
        project_id=project_id,
        document_type=document_type,
        document_ids=document_ids,
        validity_status=validity_status,
    )
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(DocumentChunk, distance)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(*filters, DocumentChunk.embedding.is_not(None))
        .order_by(distance.asc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    scored: list[tuple[DocumentChunk, float]] = []
    for chunk, value in rows:
        distance_value = float(value)
        scored.append((chunk, 1.0 - distance_value))
    return scored
