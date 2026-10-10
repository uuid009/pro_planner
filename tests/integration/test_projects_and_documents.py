import io
import zipfile

import pytest
from sqlalchemy import text

from app.db.session import get_engine


def _pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _office(prefix: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr(f"{prefix}/content.xml", "<root/>")
    return buffer.getvalue()


def _project_payload(**overrides):
    payload = {
        "name": "园区数字化改造",
        "project_type": "implementation",
        "objective": "完成一期系统上线",
        "background": "现有台账分散",
        "constraints": "不新增外部云服务",
        "plan_start_date": "2026-01-01",
        "plan_end_date": "2026-06-30",
    }
    payload.update(overrides)
    return payload


def test_vector_column_dimension_is_1024():
    with get_engine().connect() as conn:
        column_type = conn.execute(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'document_chunks'
                  AND a.attname = 'embedding'
                """
            )
        ).scalar_one()
    assert column_type == "vector(1024)"


def test_create_list_and_get_project(client):
    created = client.post("/api/projects", json=_project_payload())
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    listing = client.get("/api/projects")
    assert listing.status_code == 200
    assert any(item["id"] == project_id for item in listing.json())

    detail = client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["objective"] == "完成一期系统上线"
    assert detail.json()["plan_start_date"] == "2026-01-01"


def test_project_dates_and_missing_project(client):
    invalid = client.post(
        "/api/projects",
        json=_project_payload(plan_start_date="2026-07-01", plan_end_date="2026-01-01"),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    missing = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"


def test_upload_registers_version_and_rejects_duplicates(client):
    project = client.post("/api/projects", json=_project_payload(name="知识库项目")).json()
    files = {"file": ("方案.pdf", _pdf(), "application/pdf")}
    data = {"project_id": project["id"]}
    first = client.post("/api/documents/upload", files=files, data=data)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["document_type"] == "pdf"
    assert body["version_number"] == 1
    assert body["validity_status"] == "active"
    assert body["created_by"] == "demo-user"
    assert ".." not in body["relative_path"]
    assert body["filename"] == "方案.pdf"

    second = client.post(
        "/api/documents/upload",
        files={"file": ("另一份.pdf", _pdf(), "application/pdf")},
        data=data,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_document"
    assert second.json()["error"]["details"]["document_id"] == body["id"]

    listing = client.get("/api/documents", params={"project_id": project["id"], "document_type": "pdf"})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_upload_rejects_bad_extension_and_traversal_name(client):
    rejected = client.post(
        "/api/documents/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "unsupported_type"

    uploaded = client.post(
        "/api/documents/upload",
        files={"file": ("../../etc/passwd.pdf", _pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["filename"] == "passwd.pdf"
    assert uploaded.json()["relative_path"].endswith(".pdf")
    assert "/" not in uploaded.json()["relative_path"]


def test_upload_docx_and_xlsx(client):
    docx = client.post(
        "/api/documents/upload",
        files={"file": ("计划.docx", _office("word"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    xlsx = client.post(
        "/api/documents/upload",
        files={"file": ("任务.xlsx", _office("xl"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert docx.status_code == 200, docx.text
    assert xlsx.status_code == 200, xlsx.text
    assert {docx.json()["document_type"], xlsx.json()["document_type"]} == {"docx", "xlsx"}


def test_mismatched_vector_dimension_is_rejected_by_database():
    from app.db.models import Document, DocumentChunk, DocumentVersion
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        document = Document(
            filename="dim.pdf",
            document_type="pdf",
            sha256="a" * 64,
            relative_path="dim.pdf",
            created_by="demo-user",
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            sha256="a" * 64,
            validity_status="active",
            relative_path="dim.pdf",
        )
        session.add(version)
        session.flush()
        session.add(
            DocumentChunk(
                document_version_id=version.id,
                chunk_index=0,
                content="维度检查",
                text_hash="b" * 64,
                chunk_metadata={},
                embedding=[0.1, 0.2],
            )
        )
        with pytest.raises(Exception):
            session.flush()
    finally:
        session.rollback()
        session.close()
