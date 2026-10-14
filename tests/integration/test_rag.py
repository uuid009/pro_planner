from app.config import get_settings
from tests.helpers import make_docx, make_empty_pdf, make_pdf, make_xlsx


def _project_payload(name: str = "RAG 项目"):
    return {
        "name": name,
        "project_type": "implementation",
        "objective": "验证文档入库与混合检索",
        "background": "Phase 2",
        "constraints": "仅使用本地模型",
        "plan_start_date": "2026-01-01",
        "plan_end_date": "2026-06-30",
    }


def _use_mock_embeddings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "mock")
    monkeypatch.setattr(settings, "reranker_enabled", False)
    return settings


def test_index_and_hybrid_search_returns_traceable_evidence(client, monkeypatch):
    _use_mock_embeddings(monkeypatch)
    project = client.post("/api/projects", json=_project_payload()).json()
    uploaded = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "方案.docx",
                make_docx(
                    "项目目标是完成一期系统上线，不新增外部云服务。",
                    heading="园区数字化改造实施方案",
                    table_rows=[["任务", "验收标准"], ["台账迁移", "历史项目材料可检索"]],
                ),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"project_id": project["id"]},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["index_status"] == "pending"
    document_id = uploaded.json()["id"]

    indexed = client.post(f"/api/documents/{document_id}/index")
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["chunk_count"] >= 2
    assert indexed.json()["index_status"] == "indexed"
    assert indexed.json()["embedding_mock"] is True

    listing = client.get("/api/documents", params={"project_id": project["id"]})
    assert listing.json()[0]["chunk_count"] == indexed.json()["chunk_count"]
    assert listing.json()[0]["index_status"] == "indexed"

    search = client.post(
        "/api/retrieval/search",
        json={"query": "一期系统上线", "project_id": project["id"]},
    )
    assert search.status_code == 200, search.text
    items = search.json()["items"]
    assert items
    first = items[0]
    assert first["document_id"] == document_id
    assert first["chunk_id"]
    assert first["title"] == "方案.docx"
    assert "一期系统上线" in first["quote"] or any(
        "一期系统上线" in item["quote"] for item in items
    )
    assert first["verification_status"] in {"supported", "needs_review"}
    assert first["validity_status"] == "active"


def test_search_respects_project_filter_and_empty_query(client, monkeypatch):
    _use_mock_embeddings(monkeypatch)
    left = client.post("/api/projects", json=_project_payload("左侧")).json()
    right = client.post("/api/projects", json=_project_payload("右侧")).json()
    left_doc = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "left.pdf",
                make_pdf("左侧独有证据：防洪堤加固工期不得虚构"),
                "application/pdf",
            )
        },
        data={"project_id": left["id"]},
    ).json()
    right_doc = client.post(
        "/api/documents/upload",
        files={"file": ("right.pdf", make_pdf("右侧独有证据：变电站检修窗口"), "application/pdf")},
        data={"project_id": right["id"]},
    ).json()
    assert client.post(f"/api/documents/{left_doc['id']}/index").status_code == 200
    assert client.post(f"/api/documents/{right_doc['id']}/index").status_code == 200

    search = client.post(
        "/api/retrieval/search",
        json={"query": "防洪堤加固", "project_id": left["id"]},
    )
    assert search.status_code == 200, search.text
    titles = {item["title"] for item in search.json()["items"]}
    assert "left.pdf" in titles
    assert "right.pdf" not in titles

    empty = client.post("/api/retrieval/search", json={"query": "   "})
    assert empty.status_code == 422


def test_index_pdf_xlsx_and_reject_unreadable_pdf(client, monkeypatch):
    _use_mock_embeddings(monkeypatch)
    pdf = client.post(
        "/api/documents/upload",
        files={
            "file": ("制度.pdf", make_pdf("制度条款：不得凭空编造预算和人员。"), "application/pdf")
        },
    )
    xlsx = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "任务.xlsx",
                make_xlsx([["任务名称", "责任角色"], ["编制项目书", "策划专责"]]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert client.post(f"/api/documents/{pdf.json()['id']}/index").status_code == 200
    indexed = client.post(f"/api/documents/{xlsx.json()['id']}/index")
    assert indexed.status_code == 200, indexed.text
    search = client.post("/api/retrieval/search", json={"query": "策划专责"})
    assert any("策划专责" in item["quote"] for item in search.json()["items"])

    blank = client.post(
        "/api/documents/upload",
        files={"file": ("空白.pdf", make_empty_pdf(), "application/pdf")},
    )
    failed = client.post(f"/api/documents/{blank.json()['id']}/index")
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "parse_failed"

    missing = client.post("/api/documents/00000000-0000-0000-0000-000000000000/index")
    assert missing.status_code == 404
