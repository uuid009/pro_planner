"""解析 PDF / DOCX / XLSX。上传内容视为不可信输入，只抽取可见文本。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from app.api.errors import AppError
from app.rag.schemas import ParsedBlock

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


def parse_document(document_type: str, content: bytes, filename: str) -> list[ParsedBlock]:
    if document_type == "pdf":
        blocks = _parse_pdf(content, filename)
    elif document_type == "docx":
        blocks = _parse_docx(content)
    elif document_type == "xlsx":
        blocks = _parse_xlsx(content)
    else:
        raise AppError(400, "unsupported_type", "只支持解析 PDF、DOCX、XLSX")
    if not blocks:
        raise AppError(422, "parse_failed", "未能从文件中提取到文本")
    return blocks


def _parse_pdf(content: bytes, filename: str) -> list[ParsedBlock]:
    if fitz is None:
        raise AppError(500, "parser_unavailable", "当前环境未安装 PyMuPDF")
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise AppError(422, "parse_failed", "PDF 无法打开") from exc
    blocks: list[ParsedBlock] = []
    try:
        if document.page_count == 0:
            raise AppError(422, "parse_failed", "PDF 没有页面")
        for index, page in enumerate(document, start=1):
            text = (page.get_text("text") or "").strip()
            if not text:
                continue
            blocks.append(
                ParsedBlock(
                    text=text,
                    section=None,
                    page_number=index,
                    block_type="page",
                    metadata={"source_filename": Path(filename).name},
                )
            )
    finally:
        document.close()
    if not blocks:
        raise AppError(422, "parse_failed", "PDF 未能提取到文本，可能是扫描件或纯图片")
    return blocks


def _parse_docx(content: bytes) -> list[ParsedBlock]:
    try:
        document = DocxDocument(BytesIO(content))
    except Exception as exc:
        raise AppError(422, "parse_failed", "DOCX 无法打开") from exc
    blocks: list[ParsedBlock] = []
    section: str | None = None
    for item in _iter_docx_blocks(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style_name = item.style.name if item.style is not None else ""
            if style_name.startswith("Heading"):
                section = text
                blocks.append(
                    ParsedBlock(
                        text=text,
                        section=section,
                        block_type="heading",
                        metadata={"style": style_name},
                    )
                )
                continue
            blocks.append(
                ParsedBlock(
                    text=text,
                    section=section,
                    block_type="paragraph",
                    metadata={"style": style_name},
                )
            )
            continue
        if isinstance(item, Table):
            blocks.extend(_table_blocks(item, section))
    return blocks


def _iter_docx_blocks(document: DocxDocument):
    body = document.element.body
    mapping = {paragraph._element: paragraph for paragraph in document.paragraphs}
    mapping.update({table._element: table for table in document.tables})
    for child in body.iterchildren():
        item = mapping.get(child)
        if item is not None:
            yield item


def _table_blocks(table: Table, section: str | None) -> list[ParsedBlock]:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not rows:
        return []
    headers = rows[0]
    header_line = " | ".join(value for value in headers if value)
    blocks: list[ParsedBlock] = []
    data_rows = rows[1:] if any(headers) and len(rows) > 1 else rows
    start_index = 2 if data_rows is not rows else 1
    if header_line and data_rows is not rows:
        prefix = f"表头: {header_line}"
    else:
        prefix = "表格"
    for offset, row in enumerate(data_rows):
        if not any(row):
            continue
        if data_rows is not rows and headers:
            pairs = [f"{header}:{value}" for header, value in zip(headers, row) if value and header]
            text = "；".join(pairs) if pairs else "；".join(value for value in row if value)
        else:
            text = " | ".join(value for value in row if value)
        if not text:
            continue
        blocks.append(
            ParsedBlock(
                text=f"{prefix}。{text}",
                section=section or "表格",
                block_type="table_row",
                metadata={"row": start_index + offset, "headers": headers},
            )
        )
    return blocks


def _parse_xlsx(content: bytes) -> list[ParsedBlock]:
    try:
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise AppError(422, "parse_failed", "XLSX 无法打开") from exc
    blocks: list[ParsedBlock] = []
    try:
        for sheet in workbook.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            headers = [_cell_text(value) for value in rows[0]]
            header_line = " | ".join(value for value in headers if value)
            for row_number, row in enumerate(rows[1:], start=2):
                values = [_cell_text(value) for value in row]
                if not any(values):
                    continue
                pairs = [
                    f"{header}:{value}"
                    for header, value in zip(headers, values)
                    if value and header
                ]
                text = "；".join(pairs) if pairs else "；".join(value for value in values if value)
                located = []
                for column_index, value in enumerate(values):
                    if value:
                        located.append(f"列{column_index + 1}={value}")
                blocks.append(
                    ParsedBlock(
                        text=f"工作表:{sheet.title}。表头: {header_line}。{text}",
                        section=sheet.title,
                        block_type="sheet_row",
                        metadata={
                            "sheet": sheet.title,
                            "row": row_number,
                            "headers": headers,
                            "cells": located,
                        },
                    )
                )
    finally:
        workbook.close()
    return blocks


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
