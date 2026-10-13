"""按项目简报检索证据。证据不足时返回缺口，不补造事实。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.config import Settings
from app.rag.service import hybrid_search


def retrieve_evidence(state: dict, db: Session, settings: Settings) -> dict:
    brief = state.get("project_brief") or {}
    queries = _queries(brief, state.get("user_request") or "")
    merged: dict[str, dict] = {}
    for query in queries:
        items = hybrid_search(
            db,
            settings,
            query=query,
            project_id=_uuid(state.get("project_id")),
            libraries=list(state.get("visible_libraries") or ["public"]),
        )
        for item in items:
            merged.setdefault(str(item.chunk_id), item.model_dump(mode="json"))
    evidence = list(merged.values())[: settings.retrieval_top_k]
    gaps: list[str] = []
    if not evidence:
        gaps.append("知识库没有检索到可用证据，生成内容必须标记为待确认")
    return {
        "retrieval_queries": queries,
        "evidence_bundle": {"items": evidence, "gaps": gaps, "queries": queries},
        "status": "evidence_ready" if evidence else "evidence_insufficient",
        "model_metadata": {"node": "retrieve_evidence", "hit_count": len(evidence)},
    }


def _queries(brief: dict, user_request: str) -> list[str]:
    candidates = [
        brief.get("objective") or "",
        brief.get("background") or "",
        brief.get("constraints") or "",
        user_request,
        " ".join(brief.get("deliverables") or []),
    ]
    queries: list[str] = []
    for item in candidates:
        text = " ".join(str(item).split())
        if text and text not in queries:
            queries.append(text[:200])
    return queries[:4] or ["项目实施方案"]


def _uuid(value: object) -> UUID | None:
    if not value:
        return None
    return UUID(str(value))
