"""Embedding 接口。测试使用确定性 mock，本地权重通过 sentence-transformers 加载。"""

from __future__ import annotations

import hashlib
import logging
import math
from functools import lru_cache
from pathlib import Path

import httpx

from app.api.errors import AppError
from app.config import PROJECT_ROOT, Settings, get_settings

logger = logging.getLogger(__name__)

_BGE_ZH_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索："


def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    runtime = settings or get_settings()
    if not texts:
        return []
    if runtime.embedding_provider == "mock":
        return [_mock_vector(text, runtime.embedding_dimension) for text in texts]
    if runtime.embedding_provider == "local":
        return _local_embed(texts, runtime, is_query=False)
    if runtime.embedding_provider in {"openai_compatible", "ollama"}:
        return _http_embed(texts, runtime)
    raise AppError(500, "unsupported_embedding_provider", "不支持的 EMBEDDING_PROVIDER")


def embed_query(query: str, settings: Settings | None = None) -> list[float]:
    runtime = settings or get_settings()
    if runtime.embedding_provider == "local":
        vectors = _local_embed([query], runtime, is_query=True)
        return vectors[0]
    return embed_texts([query], runtime)[0]


def resolve_model_path(model: str) -> Path:
    path = Path(model)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _mock_vector(text: str, dimension: int) -> list[float]:
    raw = b""
    counter = 0
    payload = text.encode("utf-8")
    while len(raw) < dimension * 4:
        raw += hashlib.sha256(payload + counter.to_bytes(4, "little")).digest()
        counter += 1
    values = [
        int.from_bytes(raw[index : index + 4], "little") / 2**32 - 0.5
        for index in range(0, dimension * 4, 4)
    ]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def _local_embed(texts: list[str], settings: Settings, *, is_query: bool) -> list[list[float]]:
    model = _load_sentence_transformer(settings.embedding_model, settings.embedding_device)
    payloads = texts
    instruction = settings.embedding_query_instruction or _BGE_ZH_QUERY_INSTRUCTION
    if is_query and instruction:
        payloads = [f"{instruction}{text}" for text in texts]
    vectors = model.encode(
        payloads,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    result: list[list[float]] = []
    for vector in vectors:
        values = [float(item) for item in vector.tolist()]
        _assert_dimension(values, settings)
        result.append(values)
    return result


@lru_cache(maxsize=2)
def _load_sentence_transformer(model_name: str, device: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover
        raise AppError(
            500,
            "embedding_unavailable",
            "本地 embedding 需要 sentence-transformers，当前环境未安装",
        ) from exc
    path = resolve_model_path(model_name)
    if not path.exists():
        raise AppError(500, "embedding_model_missing", f"本地 embedding 模型不存在: {path}")
    logger.info("loading_local_embedding model=%s device=%s", path, device)
    return SentenceTransformer(str(path), device=device)


def _http_embed(texts: list[str], settings: Settings) -> list[list[float]]:
    url = settings.embedding_base_url.rstrip("/")
    if settings.embedding_provider == "ollama":
        endpoint = f"{url}/api/embed"
        payload = {"model": settings.embedding_model, "input": texts}
    else:
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        endpoint = f"{url}/embeddings"
        payload = {"model": settings.embedding_model, "input": texts}
    try:
        response = httpx.post(endpoint, json=payload, timeout=60.0)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise AppError(503, "embedding_unavailable", "本地 embedding 服务不可用") from exc
    if settings.embedding_provider == "ollama":
        vectors = body.get("embeddings") or []
    else:
        items = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") or [] for item in items]
    if len(vectors) != len(texts):
        raise AppError(502, "embedding_invalid", "embedding 服务返回数量与输入不一致")
    result = []
    for vector in vectors:
        values = [float(item) for item in vector]
        _assert_dimension(values, settings)
        result.append(values)
    return result


def _assert_dimension(values: list[float], settings: Settings) -> None:
    if len(values) != settings.embedding_dimension:
        raise AppError(
            500,
            "embedding_dimension_mismatch",
            "embedding 维度与配置不一致，已拒绝写入",
            {"expected": settings.embedding_dimension, "actual": len(values)},
        )
