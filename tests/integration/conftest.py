import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import PROJECT_ROOT, get_settings
from app.db.session import get_db, get_engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@pytest.fixture
def client(tmp_path):
    settings = get_settings()
    original_upload_dir = settings.upload_dir
    settings.upload_dir = str(tmp_path)
    connection = get_engine().connect()
    transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    settings.upload_dir = original_upload_dir
    transaction.rollback()
    connection.close()
