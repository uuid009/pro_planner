"""节点耗时与业务事件。不把完整状态或原文写入日志。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from uuid import UUID

from langgraph.errors import GraphInterrupt
from sqlalchemy.orm import Session

from app.db.models import AgentEvent

logger = logging.getLogger(__name__)
_db_lock = threading.Lock()
_bound_db: Session | None = None


def bind_db(db: Session) -> None:
    global _bound_db
    _db_lock.acquire()
    _bound_db = db


def unbind_db() -> None:
    global _bound_db
    _bound_db = None
    _db_lock.release()


def bound_db() -> Session | None:
    return _bound_db


def traced(node_name: str, func: Callable[[dict], dict]) -> Callable[[dict], dict]:
    def wrapper(state: dict) -> dict:
        started = time.perf_counter()
        try:
            update = func(state) or {}
        except GraphInterrupt:
            raise
        except Exception as exc:
            duration = _elapsed(started)
            logger.info(
                "node_failed node=%s error=%s duration_ms=%s",
                node_name,
                type(exc).__name__,
                duration,
            )
            return {
                "errors": [f"{node_name}: {type(exc).__name__}"],
                "status": "failed",
                "node_events": [_event(node_name, "end", "failed", duration, type(exc).__name__)],
            }
        duration = _elapsed(started)
        events = list(update.get("node_events") or [])
        events.append(_event(node_name, "end", "ok", duration, None))
        update["node_events"] = events
        return update

    return wrapper


def persist_node_events(db: Session, run_id: UUID, events: list[dict]) -> None:
    for event in events:
        db.add(
            AgentEvent(
                run_id=run_id,
                node_name=event["node_name"],
                event_type=event["event_type"],
                duration_ms=event.get("duration_ms"),
                status=event["status"],
                error_summary=event.get("error_summary"),
                event_metadata={"prompt_kept": False},
            )
        )
    db.commit()


def _event(node_name: str, event_type: str, status: str, duration_ms: int, error: str | None) -> dict:
    return {
        "node_name": node_name,
        "event_type": event_type,
        "status": status,
        "duration_ms": duration_ms,
        "error_summary": error,
    }


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
