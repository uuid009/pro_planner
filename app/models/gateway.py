from app.config import Settings, get_settings
from app.models.providers import chat_complete, probe_llm


def complete(messages: list[dict], settings: Settings | None = None) -> str:
    return chat_complete(settings or get_settings(), messages)


def probe(settings: Settings | None = None) -> dict:
    return probe_llm(settings or get_settings())
