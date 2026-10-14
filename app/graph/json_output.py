"""从模型文本中解析 JSON。失败时只做有限次重试。"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.models.providers import chat_complete

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def loads_json_object(text: str) -> dict:
    cleaned = _THINK.sub("", text).strip()
    cleaned = _FENCE.sub("", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出里没有 JSON 对象")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise TypeError("模型输出不是 JSON 对象")
    return payload


def complete_model(
    settings: Settings,
    messages: list[dict],
    schema: type[T],
    *,
    retries: int = 2,
) -> T:
    last_error = "未知解析错误"
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
            return schema.model_validate(loads_json_object(text))
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc).splitlines()[0][:300]
            prompt = [
                *messages,
                {"role": "assistant", "content": text[:1500]},
                {
                    "role": "user",
                    "content": f"上次输出无法通过校验：{last_error}。请只返回一个合法 JSON 对象。",
                },
            ]
    raise ValueError(last_error)


def schema_hint(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False)[:2500]
