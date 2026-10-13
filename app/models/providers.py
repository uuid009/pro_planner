"""本地 LLM 适配。默认走 vLLM 的 OpenAI 兼容接口，禁止静默回退到云端。"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.api.errors import AppError
from app.config import Settings

logger = logging.getLogger(__name__)


def openai_compatible_base(url: str) -> str:
    parsed = urlparse(url)
    base = url.rstrip("/")
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return base
    return f"{base}/v1"


def llm_models_url(settings: Settings) -> str:
    if settings.llm_provider == "ollama":
        return f"{settings.llm_base_url.rstrip('/')}/api/tags"
    return f"{openai_compatible_base(settings.llm_base_url)}/models"


def probe_llm(settings: Settings) -> dict:
    if settings.llm_provider == "mock":
        return {"ready": False, "checked": False, "detail": "mock"}
    try:
        response = httpx.get(llm_models_url(settings), timeout=0.8)
        response.raise_for_status()
        return {"ready": True, "checked": True, "detail": "ok"}
    except Exception as exc:
        logger.info("llm_probe_failed provider=%s error=%s", settings.llm_provider, type(exc).__name__)
        return {"ready": False, "checked": True, "detail": type(exc).__name__}


def chat_complete(
    settings: Settings,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int = 256,
    enable_thinking: bool = False,
) -> str:
    if settings.llm_provider == "mock":
        return "【Mock LLM】这不是真实模型输出。"
    if settings.llm_provider == "local":
        raise AppError(400, "unsupported_llm_provider", "LLM 请使用 openai_compatible 连接 vLLM")
    url = f"{openai_compatible_base(settings.llm_base_url)}/chat/completions"
    payload: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if settings.llm_provider == "openai_compatible":
        payload["chat_template_kwargs"] = {
            "enable_thinking": enable_thinking,
            "preserve_thinking": False,
        }
    try:
        response = httpx.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise AppError(503, "llm_unavailable", "本地 LLM 服务不可用") from exc
    choices = body.get("choices") or []
    if not choices:
        raise AppError(502, "llm_empty", "本地 LLM 没有返回内容")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if not str(content).strip():
        raise AppError(502, "llm_empty", "本地 LLM 没有返回内容")
    return str(content)
