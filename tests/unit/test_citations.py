from uuid import uuid4

from app.config import Settings
from app.db.models import Document, DocumentChunk, DocumentVersion
from app.rag.citations import classify_evidence, to_evidence_item


def test_empty_quote_is_unsupported():
    status, note = classify_evidence(0.2, 1.0, 0.9, "   ")
    assert status == "unsupported"
    assert "空" in note


def test_low_scores_need_review():
    status, _note = classify_evidence(0.01, 0.0, 0.05, "只有弱相关片段")
    assert status == "needs_review"


def test_evidence_item_keeps_traceable_ids():
    settings = Settings(
        database_url="postgresql://postgres:secret@127.0.0.1:5432/mydb",
        llm_provider="mock",
        embedding_provider="mock",
        context_budget_chars=20,
    )
    document = Document(
        id=uuid4(),
        filename="方案.docx",
        document_type="docx",
        sha256="a" * 64,
        relative_path="a.docx",
        created_by="demo-user",
    )
    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_number=1,
        sha256="a" * 64,
        validity_status="active",
        relative_path="a.docx",
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_version_id=version.id,
        chunk_index=0,
        section="目标",
        page_number=3,
        content="完成一期系统上线，并保留历史项目材料检索能力。",
        text_hash="b" * 64,
        chunk_metadata={},
    )
    item = to_evidence_item(
        chunk,
        document,
        version,
        rrf_score=0.03,
        lexical_score=1.0,
        vector_score=0.8,
        settings=settings,
    )
    assert item.chunk_id == chunk.id
    assert item.document_id == document.id
    assert item.page_number == 3
    assert item.quote.endswith("…")
    assert item.verification_status == "supported"
