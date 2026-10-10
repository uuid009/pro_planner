"""业务表。LangGraph checkpoint 表由官方 PostgresSaver 单独管理。"""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import SCHEMA_EMBEDDING_DIMENSION
from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "plan_end_date IS NULL OR plan_start_date IS NULL OR plan_start_date <= plan_end_date",
            name="ck_projects_date_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_type: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    constraints: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan_start_date: Mapped[date | None] = mapped_column(Date)
    plan_end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(back_populates="project")
    runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    project: Mapped[Project | None] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document_version")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_document_chunks_order"),
        Index("ix_document_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(String(300))
    page_number: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 使用 simple 配置生成词条，不能当作中文分词已解决。检索层会另做关键词补充。
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
    )
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(SCHEMA_EMBEDDING_DIMENSION))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (UniqueConstraint("thread_id", name="uq_workflow_runs_thread_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128))
    branch_label: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="runs")


class ProjectTask(Base):
    __tablename__ = "project_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("artifact_versions.id", ondelete="SET NULL")
    )
    task_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_role: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    dependency_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deliverables: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "artifact_type", "version_number", name="uq_artifact_versions_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL")
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("artifact_versions.id", ondelete="SET NULL")
    )
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("artifact_versions.id", ondelete="SET NULL")
    )
    demo_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(300), nullable=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
