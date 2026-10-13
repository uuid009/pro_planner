from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.rag.schemas import EvidenceItem
from app.rag.service import hybrid_search

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    project_id: UUID | None = None
    document_type: str | None = None
    document_ids: list[UUID] | None = None
    validity_status: str = "active"

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("检索查询不能为空")
        return cleaned


class SearchResponse(BaseModel):
    query: str
    embedding_provider: str
    embedding_mock: bool
    reranker_enabled: bool
    items: list[EvidenceItem]


@router.post("/search", response_model=SearchResponse)
def search_documents(payload: SearchRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    items = hybrid_search(
        db,
        settings,
        query=payload.query,
        project_id=payload.project_id,
        document_type=payload.document_type,
        document_ids=payload.document_ids,
        validity_status=payload.validity_status,
    )
    return SearchResponse(
        query=payload.query.strip(),
        embedding_provider=settings.embedding_provider,
        embedding_mock=settings.embedding_mock,
        reranker_enabled=settings.reranker_enabled and not settings.embedding_mock,
        items=items,
    )
