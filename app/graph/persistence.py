"""PostgreSQL Checkpointer。连接池在应用启动时创建，不在每次请求里重建。"""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_saver: PostgresSaver | None = None
_ready_error: str | None = None


def init_checkpointer(database_url: str) -> None:
    global _pool, _saver, _ready_error
    if _saver is not None:
        return
    try:
        _pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=8,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        _saver = PostgresSaver(_pool)
        _saver.setup()
        with _pool.connection() as conn:
            conn.execute("SELECT 1")
        _ready_error = None
        logger.info("langgraph_checkpointer_ready")
    except Exception as exc:  # noqa: BLE001 检查点初始化失败不能阻止应用启动
        _ready_error = type(exc).__name__
        logger.info("langgraph_checkpointer_init_failed error=%s", type(exc).__name__)
        close_checkpointer()
        _ready_error = type(exc).__name__


def close_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        _pool.close()
    _pool = None
    _saver = None


def get_checkpointer() -> PostgresSaver:
    if _saver is None:
        raise RuntimeError("LangGraph Checkpointer 尚未初始化")
    return _saver


def checkpointer_status() -> dict:
    if _saver is None or _pool is None:
        return {"ready": False, "error": _ready_error or "not_initialized"}
    try:
        with _pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"ready": True, "error": None}
    except Exception as exc:  # noqa: BLE001 状态查询只返回异常类型
        return {"ready": False, "error": type(exc).__name__}
