"""从模型文本中解析 JSON。失败时只做有限次重试，不静默编造。"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.models.providers import chat_complete

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def complete_model(
    settings: Settings,
    messages: list[dict],
    model_type: type[T],
    *,
    retries: int = 2,
) -> T:
    last_error = "模型输出无法解析"
    prompt = list(messages)
    for _ in range(retries + 1):
        text = chat_complete(
            settings,
            prompt,
            temperature=0.2,
            max_tokens=1800,
            enable_thinking=False,
        )
        try:
            payload = extract_json(text)
            return model_type.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc).splitlines()[0][:240]
            prompt = [
                *messages,
                {"role": "assistant", "content": text[:1500]},
                {
                    "role": "user",
                    "content": f"上次输出无法解析：{last_error}。请只返回一个 JSON 对象，不要解释。",
                },
            ]
    raise ValueError(last_error)


def extract_json(text: str) -> object:
    cleaned = _THINK.sub("", text).strip()
    cleaned = _FENCE.sub("", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(cleaned[start : end + 1])
