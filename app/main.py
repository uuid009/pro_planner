"""FastAPI 入口。"""

from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.routes_auth import router as auth_router
from app.api.routes_documents import router as documents_router
from app.api.routes_projects import router as projects_router
from app.api.routes_proposals import router as proposals_router
from app.api.routes_retrieval import router as retrieval_router
from app.api.routes_workflows import router as workflows_router
from app.config import get_settings
from app.graph.persistence import checkpointer_status, close_checkpointer, init_checkpointer
from app.graph.workflow import reset_compiled_graph
from app.models.gateway import probe


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.artifact_dir).mkdir(parents=True, exist_ok=True)
    init_checkpointer(settings.database_url)
    yield
    reset_compiled_graph()
    close_checkpointer()


app = FastAPI(title="EnterprisePlan AI", version=__version__, lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(proposals_router)
app.include_router(documents_router)
app.include_router(retrieval_router)
app.include_router(workflows_router)


@app.get("/health")
def health():
    settings = get_settings()
    database = "error"
    pgvector_version = None
    try:
        with (
            psycopg.connect(settings.database_url, connect_timeout=5) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
            pgvector_version = row[0] if row else None
        database = "ok"
    except Exception as exc:  # noqa: BLE001 健康检查只暴露异常类型，避免泄露连接信息
        # 只返回异常类型，避免把连接串、密码或 SQL 细节写进响应。
        payload = _health_payload(settings, database, pgvector_version, type(exc).__name__)
        return JSONResponse(status_code=503, content=payload)

    return _health_payload(settings, database, pgvector_version, None)


def _health_payload(settings, database: str, pgvector_version: str | None, error: str | None):
    body = {
        "status": "ok" if database == "ok" else "degraded",
        "app_version": __version__,
        "database": database,
        "pgvector": pgvector_version,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "llm_mock": settings.llm_mock,
        "embedding_mock": settings.embedding_mock,
        "mock_mode": settings.mock_mode,
        "embedding_dimension": settings.embedding_dimension,
        "llm_ready": probe(settings)["ready"] if not settings.llm_mock else False,
        "checkpointer": checkpointer_status(),
        "app_env": settings.app_env,
    }
    if error:
        body["database_error"] = error
    return body
