"""索引入库与混合检索编排。"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.errors import AppError
from app.config import Settings
from app.db.models import Document, DocumentChunk, DocumentVersion
from app.rag.chunking import chunk_blocks
from app.rag.citations import to_evidence_item
from app.rag.embeddings import embed_query, embed_texts
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.lexical_search import lexical_search
from app.rag.parsers import parse_document
from app.rag.reranking import rerank_evidence
from app.rag.schemas import EvidenceItem
from app.rag.vector_search import vector_search
from app.services.document_service import safe_storage_path

logger = logging.getLogger(__name__)


def latest_version(document: Document) -> DocumentVersion:
    if not document.versions:
        raise AppError(409, "version_missing", "文档尚未登记版本")
    return max(document.versions, key=lambda item: item.version_number)


def index_status_for(chunk_count: int) -> str:
    return "indexed" if chunk_count > 0 else "pending"


def count_chunks(db: Session, version_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.document_version_id == version_id
            )
        )
        or 0
    )


def index_document(db: Session, settings: Settings, document_id: UUID) -> dict:
    document = db.scalar(
        select(Document)
        .options(selectinload(Document.versions))
        .where(Document.id == document_id)
    )
    if document is None:
        raise AppError(404, "document_not_found", "文档不存在")
    version = latest_version(document)
    path = safe_storage_path(settings.upload_dir, document.relative_path)
    if not path.is_file():
        raise AppError(404, "file_missing", "上传文件已丢失，无法解析")
    content = path.read_bytes()
    blocks = parse_document(document.document_type, content, document.filename)
    drafts = chunk_blocks(blocks, settings)
    if not drafts:
        raise AppError(422, "chunk_failed", "解析结果无法切分成有效片段")
    vectors = embed_texts([draft.content for draft in drafts], settings)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
    for draft, vector in zip(drafts, vectors, strict=True):
        db.add(
            DocumentChunk(
                document_version_id=version.id,
                chunk_index=draft.chunk_index,
                section=draft.section,
                page_number=draft.page_number,
                content=draft.content,
                text_hash=draft.text_hash,
                chunk_metadata=draft.metadata,
                embedding=vector,
            )
        )
    db.commit()
    logger.info(
        "document_indexed document_id=%s version=%s chunks=%s provider=%s mock=%s",
        document.id,
        version.version_number,
        len(drafts),
        settings.embedding_provider,
        settings.embedding_mock,
    )
    return {
        "document_id": document.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "chunk_count": len(drafts),
        "index_status": "indexed",
        "embedding_provider": settings.embedding_provider,
        "embedding_mock": settings.embedding_mock,
    }


def hybrid_search(
    db: Session,
    settings: Settings,
    *,
    query: str,
    project_id: UUID | None = None,
    document_type: str | None = None,
    document_ids: list[UUID] | None = None,
    validity_status: str = "active",
) -> list[EvidenceItem]:
    cleaned = query.strip()
    if not cleaned:
        raise AppError(400, "empty_query", "检索查询不能为空")
    candidate_limit = settings.retrieval_top_k
    lexical_hits = lexical_search(
        db,
        cleaned,
        limit=candidate_limit,
        project_id=project_id,
        document_type=document_type,
        document_ids=document_ids,
        validity_status=validity_status,
    )
    query_vector = embed_query(cleaned, settings)
    vector_hits = vector_search(
        db,
        query_vector,
        limit=candidate_limit,
        project_id=project_id,
        document_type=document_type,
        document_ids=document_ids,
        validity_status=validity_status,
    )
    lexical_ids = [str(chunk.id) for chunk, _score in lexical_hits]
    vector_ids = [str(chunk.id) for chunk, _score in vector_hits]
    fused = reciprocal_rank_fusion([lexical_ids, vector_ids])
    if not fused:
        return []
    chunk_map: dict[str, DocumentChunk] = {}
    lexical_scores = {str(chunk.id): score for chunk, score in lexical_hits}
    vector_scores = {str(chunk.id): score for chunk, score in vector_hits}
    for chunk, _score in lexical_hits + vector_hits:
        chunk_map[str(chunk.id)] = chunk
    fused_ids = [item_id for item_id, _score in fused[: candidate_limit]]
    missing = [item_id for item_id in fused_ids if item_id not in chunk_map]
    if missing:
        extra = db.scalars(
            select(DocumentChunk).where(DocumentChunk.id.in_(missing))
        ).all()
        for chunk in extra:
            chunk_map[str(chunk.id)] = chunk
    version_ids = {chunk.document_version_id for chunk in chunk_map.values()}
    versions = {
        version.id: version
        for version in db.scalars(
            select(DocumentVersion)
            .options(selectinload(DocumentVersion.document))
            .where(DocumentVersion.id.in_(version_ids))
        )
    }
    evidence: list[EvidenceItem] = []
    rrf_scores = dict(fused)
    for chunk_id in fused_ids:
        chunk = chunk_map.get(chunk_id)
        if chunk is None:
            continue
        version = versions.get(chunk.document_version_id)
        if version is None:
            continue
        evidence.append(
            to_evidence_item(
                chunk,
                version.document,
                version,
                rrf_score=rrf_scores[chunk_id],
                lexical_score=lexical_scores.get(chunk_id),
                vector_score=vector_scores.get(chunk_id),
                settings=settings,
            )
        )
    return rerank_evidence(cleaned, evidence, settings)
