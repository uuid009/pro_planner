"""批准后写入草稿快照、DOCX 和 XLSX。同一运行的同一内容不会新增版本。"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.config import Settings
from app.db.models import ArtifactVersion, EvidenceLink
from app.exporting.diff import artifact_plain_text, unified_text_diff
from app.exporting.office import build_plan_xlsx, build_proposal_docx
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
        "note": "演示用户批准的草稿快照。同一次批准会另存 DOCX/XLSX，那些文件也不是正式发布。",
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

    return _store_bytes(
        db,
        settings,
        project_id=project_id,
        run_id=run_id,
        artifact_type="draft_snapshot",
        suffix=".json",
        content=raw,
        summary=_summary(proposal, tasks),
        parent_version_id=None,
        evidence_items=evidence_items,
        field_path="proposal",
    )


def persist_approved_exports(
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
    snapshot = persist_approved_snapshot(
        db,
        settings,
        project_id=project_id,
        run_id=run_id,
        proposal=proposal,
        tasks=tasks,
        evidence_items=evidence_items,
        prompt_version=prompt_version,
    )
    title = str(proposal.get("title") or "项目书草稿")
    _store_bytes(
        db,
        settings,
        project_id=project_id,
        run_id=run_id,
        artifact_type="proposal_docx",
        suffix=".docx",
        content=build_proposal_docx(proposal, tasks, evidence_items, prompt_version=prompt_version),
        summary=f"{title} 项目书。演示确认草稿，不是正式发布文件。",
        parent_version_id=snapshot.id,
        evidence_items=evidence_items,
        field_path="proposal",
    )
    _store_bytes(
        db,
        settings,
        project_id=project_id,
        run_id=run_id,
        artifact_type="plan_xlsx",
        suffix=".xlsx",
        content=build_plan_xlsx(tasks, title=title, prompt_version=prompt_version),
        summary=f"任务 {len(tasks)} 条。演示确认草稿，不是正式批准计划。",
        parent_version_id=snapshot.id,
        evidence_items=evidence_items,
        field_path="plan",
    )
    return snapshot


def compare_artifacts(db: Session, settings: Settings, left_id: UUID, right_id: UUID) -> dict:
    left = get_artifact(db, left_id)
    right = get_artifact(db, right_id)
    if left.project_id != right.project_id:
        raise AppError(409, "artifact_project_mismatch", "只能比较同一项目下的产物")
    diff = unified_text_diff(
        f"{left.artifact_type}-v{left.version_number}",
        artifact_plain_text(settings, left),
        f"{right.artifact_type}-v{right.version_number}",
        artifact_plain_text(settings, right),
    )
    return {
        "kind": "text_diff",
        "note": "这是文本级差异，不是语义级版本比较。",
        "left_id": left.id,
        "right_id": right.id,
        "diff": diff,
    }


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


def _store_bytes(
    db: Session,
    settings: Settings,
    *,
    project_id: UUID,
    run_id: UUID,
    artifact_type: str,
    suffix: str,
    content: bytes,
    summary: str,
    parent_version_id: UUID | None,
    evidence_items: list[dict],
    field_path: str,
) -> ArtifactVersion:
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.run_id == run_id,
            ArtifactVersion.artifact_type == artifact_type,
            ArtifactVersion.sha256 == digest,
        )
    )
    if existing is not None:
        return existing

    storage_name = f"{uuid4().hex}{suffix}"
    target = safe_storage_path(settings.artifact_dir, storage_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{suffix}.tmp")
    temporary.write_bytes(content)
    temporary.replace(target)
    version_number = int(
        db.scalar(
            select(func.coalesce(func.max(ArtifactVersion.version_number), 0)).where(
                ArtifactVersion.project_id == project_id,
                ArtifactVersion.artifact_type == artifact_type,
            )
        )
        or 0
    ) + 1
    artifact = ArtifactVersion(
        project_id=project_id,
        run_id=run_id,
        artifact_type=artifact_type,
        version_number=version_number,
        parent_version_id=parent_version_id,
        relative_path=storage_name,
        sha256=digest,
        summary=summary,
        review_status="demo_approved",
    )
    db.add(artifact)
    db.flush()
    _link_evidence(db, artifact.id, evidence_items, field_path)
    db.commit()
    db.refresh(artifact)
    return artifact


def _link_evidence(db: Session, artifact_id: UUID, evidence_items: list[dict], field_path: str) -> None:
    for item in evidence_items:
        db.add(
            EvidenceLink(
                artifact_version_id=artifact_id,
                field_path=field_path,
                chunk_id=_uuid_or_none(item.get("chunk_id")),
                quote=str(item.get("quote") or "")[:500],
                verification_status=str(item.get("verification_status") or "needs_review"),
                verification_note="引用只说明草稿使用了该片段，不代表内容已经过业务批准",
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
