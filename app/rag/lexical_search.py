"""PostgreSQL 全文检索 + 中文关键词补充。simple 分词不能覆盖中文切词。"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Integer, func, literal, or_, select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk, DocumentVersion

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
LIKE_ESCAPE = "\\"


def extract_terms(query: str, limit: int = 20) -> list[str]:
    terms: list[str] = []
    stripped = query.strip()
    if stripped:
        terms.append(stripped)
    terms.extend(WORD_RE.findall(query))
    for run in CJK_RE.findall(query):
        terms.append(run)
        if len(run) >= 4:
            terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if not term or key in seen or len(term) > 50:
            continue
        seen.add(key)
        unique.append(term)
        if len(unique) >= limit:
            break
    return unique


def escape_like(term: str) -> str:
    return (
        term.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def common_document_filters(
    *,
    project_id: UUID | None,
    document_type: str | None,
    document_ids: list[UUID] | None,
    validity_status: str,
    libraries: list[str] | None = None,
):
    filters = [DocumentVersion.validity_status == validity_status]
    if libraries is not None:
        filters.append(Document.library.in_(libraries))
    if project_id is not None:
        filters.append(Document.project_id == project_id)
    if document_type is not None:
        filters.append(Document.document_type == document_type)
    if document_ids:
        filters.append(Document.id.in_(document_ids))
    return filters


def lexical_search(
    db: Session,
    query: str,
    *,
    limit: int,
    project_id: UUID | None = None,
    document_type: str | None = None,
    document_ids: list[UUID] | None = None,
    validity_status: str = "active",
    libraries: list[str] | None = None,
) -> list[tuple[DocumentChunk, float]]:
    terms = extract_terms(query)
    if not terms:
        return []
    filters = common_document_filters(
        project_id=project_id,
        document_type=document_type,
        document_ids=document_ids,
        validity_status=validity_status,
        libraries=libraries,
    )
    ts_query = func.plainto_tsquery("simple", query)
    like_clauses = [
        DocumentChunk.content.ilike(f"%{escape_like(term)}%", escape=LIKE_ESCAPE)
        for term in terms
    ]
    rank = func.coalesce(func.ts_rank_cd(DocumentChunk.content_tsv, ts_query), 0)
    keyword_hits = literal(0)
    for term in terms:
        keyword_hits = keyword_hits + func.cast(
            DocumentChunk.content.ilike(f"%{escape_like(term)}%", escape=LIKE_ESCAPE),
            Integer,
        )
    stmt = (
        select(DocumentChunk, rank, keyword_hits)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(*filters, or_(DocumentChunk.content_tsv.op("@@")(ts_query), *like_clauses))
        .order_by((rank + keyword_hits).desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    scored: list[tuple[DocumentChunk, float]] = []
    for chunk, ts_rank, hits in rows:
        score = float(ts_rank or 0.0) + float(hits or 0) / max(len(terms), 1)
        scored.append((chunk, score))
    return scored
