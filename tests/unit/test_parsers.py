import pytest

from app.api.errors import AppError
from app.rag.parsers import parse_document
from tests.helpers import make_docx, make_empty_pdf, make_pdf, make_xlsx


def test_pdf_keeps_page_number():
    blocks = parse_document("pdf", make_pdf("项目目标：完成一期系统上线"), "plan.pdf")
    assert blocks[0].page_number == 1
    assert "一期系统上线" in blocks[0].text


def test_empty_pdf_is_rejected():
    with pytest.raises(AppError) as exc:
        parse_document("pdf", make_empty_pdf(), "blank.pdf")
    assert exc.value.code == "parse_failed"


def test_docx_keeps_heading_and_table_headers():
    blocks = parse_document(
        "docx",
        make_docx(
            "现有台账分散。",
            heading="建设必要性",
            table_rows=[["任务", "验收标准"], ["台账迁移", "历史材料可检索"]],
        ),
        "plan.docx",
    )
    assert any(block.block_type == "heading" and block.section == "建设必要性" for block in blocks)
    table_rows = [block for block in blocks if block.block_type == "table_row"]
    assert table_rows
    assert "台账迁移" in table_rows[0].text
    assert "验收标准" in table_rows[0].text


def test_xlsx_keeps_sheet_and_cell_location():
    blocks = parse_document(
        "xlsx",
        make_xlsx([["任务名称", "责任角色"], ["风险排查", "项目经理"]], sheet="任务表"),
        "plan.xlsx",
    )
    assert blocks[0].section == "任务表"
    assert blocks[0].metadata["row"] == 2
    assert "风险排查" in blocks[0].text
    assert "项目经理" in blocks[0].text
