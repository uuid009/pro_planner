from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ParsedBlock(BaseModel):
    text: str
    section: str | None = None
    page_number: int | None = None
    block_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkDraft(BaseModel):
    content: str
    section: str | None = None
    page_number: int | None = None
    chunk_index: int
    text_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    evidence_id: str
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    title: str
    quote: str
    page_number: int | None = None
    section: str | None = None
    document_type: str
    validity_status: str
    lexical_score: float | None = None
    vector_score: float | None = None
    rrf_score: float
    rerank_score: float | None = None
    verification_status: Literal["supported", "unsupported", "needs_review"]
    verification_note: str = ""
