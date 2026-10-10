from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def to_sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url


_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(to_sqlalchemy_url(get_settings().database_url), pool_pre_ping=True)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
