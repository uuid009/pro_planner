from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import ArtifactVersion, Project, WorkflowRun
from app.db.session import get_engine
from app.services.artifact_service import persist_approved_snapshot


def test_same_snapshot_does_not_create_another_version(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path))
    connection = get_engine().connect()
    transaction = connection.begin()
    db = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    try:
        project = Project(name="快照项目", objective="上线")
        run = WorkflowRun(project=project, thread_id=uuid4().hex, status="running")
        db.add(run)
        db.commit()
        payload = {
            "project_id": project.id,
            "run_id": run.id,
            "proposal": {"title": "项目书"},
            "tasks": [{"task_id": "T1", "title": "准备"}],
            "evidence_items": [{"quote": "原文", "verification_status": "needs_review"}],
            "prompt_version": "phase3-v1",
        }
        first = persist_approved_snapshot(db, settings, **payload)
        second = persist_approved_snapshot(db, settings, **payload)
        assert first.id == second.id
        count = db.scalar(
            select(func.count())
            .select_from(ArtifactVersion)
            .where(ArtifactVersion.run_id == run.id)
        )
        assert count == 1
        assert db.get(ArtifactVersion, first.id).version_number == 1
        changed = persist_approved_snapshot(
            db,
            settings,
            **{**payload, "proposal": {"title": "修订后的项目书"}},
        )
        assert changed.id != first.id
        assert changed.version_number == 2
        assert len(list(tmp_path.glob("*.json"))) == 2
    finally:
        db.close()
        transaction.rollback()
        connection.close()
