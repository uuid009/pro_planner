from __future__ import annotations

from uuid import UUID

from app.config import Settings
from app.db.models import Document, DocumentChunk, DocumentVersion
from app.rag.schemas import EvidenceItem


def to_evidence_item(
    chunk: DocumentChunk,
    document: Document,
    version: DocumentVersion,
    *,
    rrf_score: float,
    lexical_score: float | None,
    vector_score: float | None,
    settings: Settings,
) -> EvidenceItem:
    quote = _clip(chunk.content, settings.context_budget_chars)
    verification_status, note = classify_evidence(rrf_score, lexical_score, vector_score, quote)
    return EvidenceItem(
        evidence_id=str(chunk.id),
        document_id=document.id,
        document_version_id=version.id,
        chunk_id=chunk.id,
        title=document.filename,
        quote=quote,
        page_number=chunk.page_number,
        section=chunk.section,
        document_type=document.document_type,
        validity_status=version.validity_status,
        lexical_score=lexical_score,
        vector_score=vector_score,
        rrf_score=rrf_score,
        verification_status=verification_status,
        verification_note=note,
    )


def classify_evidence(
    rrf_score: float,
    lexical_score: float | None,
    vector_score: float | None,
    quote: str,
) -> tuple[str, str]:
    if not quote.strip():
        return "unsupported", "检索命中但正文为空"
    if (vector_score is not None and vector_score < 0.15) and (
        lexical_score is None or lexical_score < 0.2
    ):
        return "needs_review", "相关度偏低，生成时不得当作已核实事实"
    return "supported", "来自检索到的原文片段，不代表制度或业务已批准"


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def evidence_key(document_id: UUID, chunk_id: UUID) -> str:
    return f"{document_id}:{chunk_id}"
