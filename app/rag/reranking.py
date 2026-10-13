"""可选本地 Reranker。关闭或 mock 时按融合分截断，不假装已经语义重排。"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.api.errors import AppError
from app.config import PROJECT_ROOT, Settings
from app.rag.schemas import EvidenceItem

logger = logging.getLogger(__name__)


def rerank_evidence(
    query: str,
    items: list[EvidenceItem],
    settings: Settings,
) -> list[EvidenceItem]:
    if not items:
        return []
    top_n = min(settings.rerank_top_n, len(items))
    if settings.embedding_provider == "mock" or not settings.reranker_enabled:
        return items[:top_n]
    scores = _predict_scores(query, [item.quote for item in items], settings)
    ranked = sorted(zip(items, scores), key=lambda pair: pair[1], reverse=True)
    result: list[EvidenceItem] = []
    for item, score in ranked[:top_n]:
        updated = item.model_copy(update={"rerank_score": float(score)})
        result.append(updated)
    return result


def _predict_scores(query: str, passages: list[str], settings: Settings) -> list[float]:
    model = _load_cross_encoder(settings.reranker_model, settings.reranker_device)
    pairs = [(query, passage) for passage in passages]
    raw = model.predict(pairs, convert_to_numpy=True, show_progress_bar=False)
    return [float(value) for value in raw]


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str, device: str):
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover
        raise AppError(
            500,
            "reranker_unavailable",
            "本地 reranker 需要 sentence-transformers，当前环境未安装",
        ) from exc
    path = Path(model_name)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise AppError(500, "reranker_model_missing", f"本地 reranker 模型不存在: {path}")
    logger.info("loading_local_reranker model=%s device=%s", path, device)
    return CrossEncoder(str(path), device=device)
