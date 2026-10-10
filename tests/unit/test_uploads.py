from io import BytesIO
from zipfile import ZipFile

import pytest

from app.api.errors import AppError
from app.services.document_service import detect_document_type, safe_storage_path


def _office_bytes(*names: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        for name in names:
            archive.writestr(name, "<root/>")
    return buffer.getvalue()


def test_pdf_magic_is_required():
    assert detect_document_type("plan.pdf", b"%PDF-1.4\n") == "pdf"
    with pytest.raises(AppError, match="PDF"):
        detect_document_type("plan.pdf", b"not a pdf")


def test_office_type_must_match_internal_parts():
    assert detect_document_type("plan.docx", _office_bytes("word/document.xml")) == "docx"
    assert detect_document_type("plan.xlsx", _office_bytes("xl/workbook.xml")) == "xlsx"
    with pytest.raises(AppError, match="DOCX"):
        detect_document_type("plan.docx", _office_bytes("xl/workbook.xml"))


def test_unknown_extension_is_rejected():
    with pytest.raises(AppError, match="只允许上传"):
        detect_document_type("notes.txt", b"hello")


def test_storage_path_stays_inside_upload_dir(tmp_path):
    target = safe_storage_path(str(tmp_path), "abc.pdf")
    assert target.parent == tmp_path.resolve()
    with pytest.raises(AppError, match="路径不合法"):
        safe_storage_path(str(tmp_path), "../outside.pdf")
