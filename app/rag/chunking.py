"""按标题、段落和表格行切分，超长文本再按字数切分并保留 overlap。"""

from __future__ import annotations

import hashlib

from app.config import Settings
from app.rag.schemas import ChunkDraft, ParsedBlock


def chunk_blocks(blocks: list[ParsedBlock], settings: Settings) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    buffer: list[str] = []
    buffer_section: str | None = None
    buffer_page: int | None = None
    buffer_meta: dict = {}

    def flush() -> None:
        nonlocal buffer, buffer_section, buffer_page, buffer_meta
        text = "\n".join(part for part in buffer if part).strip()
        if text:
            _emit(drafts, text, buffer_section, buffer_page, buffer_meta, settings)
        buffer = []
        buffer_section = None
        buffer_page = None
        buffer_meta = {}

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.block_type == "heading":
            flush()
            _emit(
                drafts,
                text,
                block.section,
                block.page_number,
                {"block_type": block.block_type, **block.metadata},
                settings,
            )
            continue
        if block.block_type in {"table_row", "sheet_row"}:
            flush()
            _emit(
                drafts,
                text,
                block.section,
                block.page_number,
                {"block_type": block.block_type, **block.metadata},
                settings,
            )
            continue
        if buffer and (
            len("\n".join(buffer)) + 1 + len(text) > settings.chunk_size
            or (buffer_section and block.section and buffer_section != block.section)
        ):
            flush()
        if not buffer:
            buffer_section = block.section
            buffer_page = block.page_number
            buffer_meta = {"block_type": block.block_type, **block.metadata}
        buffer.append(text)
        if buffer_page is None:
            buffer_page = block.page_number
    flush()
    for index, draft in enumerate(drafts):
        draft.chunk_index = index
    return drafts


def _emit(
    drafts: list[ChunkDraft],
    text: str,
    section: str | None,
    page_number: int | None,
    metadata: dict,
    settings: Settings,
) -> None:
    pieces = _split_with_overlap(text, settings.chunk_size, settings.chunk_overlap)
    for piece in pieces:
        drafts.append(
            ChunkDraft(
                content=piece,
                section=section,
                page_number=page_number,
                chunk_index=len(drafts),
                text_hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                metadata=dict(metadata),
            )
        )


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return parts
