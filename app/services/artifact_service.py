"""批准后的草稿快照。正式 DOCX/XLSX 导出留到 Phase 5。同一内容重复提交不会新增版本。"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import Settings
from app.db.models import ArtifactVersion, EvidenceLink
from app.services.document_service import safe_storage_path


def persist_approved_snapshot(
    db: Session,
    settings: Settings,
    *,
    project_id: UUID,
    run_id: UUID,
    proposal: dict,
    tasks: list[dict],
    evidence_items: list[dict],
    prompt_version: str | None,
) -> ArtifactVersion:
    payload = {
        "kind": "draft_snapshot",
        "note": "演示用户批准的草稿快照，不是正式导出的 DOCX/XLSX。",
        "prompt_version": prompt_version,
        "proposal": proposal,
        "tasks": tasks,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.run_id == run_id,
            ArtifactVersion.artifact_type == "draft_snapshot",
            ArtifactVersion.sha256 == digest,
        )
    )
    if existing is not None:
        return existing

    storage_name = f"{uuid4().hex}.json"
    target = safe_storage_path(settings.artifact_dir, storage_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_bytes(raw)
    temporary.replace(target)

    version_number = int(
        db.scalar(
            select(func.coalesce(func.max(ArtifactVersion.version_number), 0)).where(
                ArtifactVersion.project_id == project_id,
                ArtifactVersion.artifact_type == "draft_snapshot",
            )
        )
        or 0
    ) + 1
    artifact = ArtifactVersion(
        project_id=project_id,
        run_id=run_id,
        artifact_type="draft_snapshot",
        version_number=version_number,
        relative_path=storage_name,
        sha256=digest,
        summary=_summary(proposal, tasks),
        review_status="demo_approved",
    )
    db.add(artifact)
    db.flush()
    for item in evidence_items:
        chunk_id = _uuid_or_none(item.get("chunk_id"))
        db.add(
            EvidenceLink(
                artifact_version_id=artifact.id,
                field_path="proposal",
                chunk_id=chunk_id,
                quote=str(item.get("quote") or "")[:500],
                verification_status=str(item.get("verification_status") or "needs_review"),
                verification_note="引用只说明草稿使用了该片段，不代表内容已经过业务批准",
            )
        )
    db.commit()
    db.refresh(artifact)
    return artifact


def list_project_artifacts(db: Session, project_id: UUID) -> list[ArtifactVersion]:
    return list(
        db.scalars(
            select(ArtifactVersion)
            .where(ArtifactVersion.project_id == project_id)
            .order_by(ArtifactVersion.created_at.asc())
        )
    )


def get_artifact(db: Session, artifact_id: UUID) -> ArtifactVersion:
    artifact = db.get(ArtifactVersion, artifact_id)
    if artifact is None:
        raise AppError(404, "artifact_not_found", "产物不存在")
    return artifact


def list_evidence(db: Session, artifact_id: UUID) -> list[EvidenceLink]:
    get_artifact(db, artifact_id)
    return list(
        db.scalars(
            select(EvidenceLink)
            .where(EvidenceLink.artifact_version_id == artifact_id)
            .order_by(EvidenceLink.created_at.asc())
        )
    )


def _summary(proposal: dict, tasks: list[dict]) -> str:
    title = proposal.get("title") or "项目书草稿"
    return f"{title}；任务 {len(tasks)} 条。这是草稿快照，不是正式文档导出。"


def _uuid_or_none(value: object) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None
