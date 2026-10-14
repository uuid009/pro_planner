from app.config import Settings
from app.rag.chunking import chunk_blocks
from app.rag.schemas import ParsedBlock


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://postgres:secret@127.0.0.1:5432/mydb",
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "chunk_size": 40,
        "chunk_overlap": 8,
    }
    values.update(overrides)
    return Settings(**values)


def test_chunking_keeps_headings_and_table_rows():
    blocks = [
        ParsedBlock(text="项目背景", section="项目背景", block_type="heading"),
        ParsedBlock(
            text="现有台账分散，需要统一编制流程。", section="项目背景", block_type="paragraph"
        ),
        ParsedBlock(
            text="表头: 任务 | 验收。任务:台账迁移；验收:可检索",
            section="实施内容",
            block_type="table_row",
            metadata={"headers": ["任务", "验收"], "row": 2},
        ),
    ]
    drafts = chunk_blocks(blocks, _settings())
    assert drafts[0].section == "项目背景"
    assert drafts[0].content == "项目背景"
    assert any("台账迁移" in item.content for item in drafts)
    assert any(item.metadata.get("block_type") == "table_row" for item in drafts)
    assert [item.chunk_index for item in drafts] == list(range(len(drafts)))


def test_long_text_is_split_with_overlap():
    text = "建设必要性。" + ("统一项目书编制。" * 8)
    drafts = chunk_blocks(
        [ParsedBlock(text=text, section="必要性", block_type="page", page_number=2)],
        _settings(chunk_size=30, chunk_overlap=6),
    )
    assert len(drafts) >= 2
    assert drafts[0].page_number == 2
    assert drafts[1].content.startswith(drafts[0].content[-6:])
