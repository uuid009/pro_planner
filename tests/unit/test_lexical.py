from app.rag.lexical_search import escape_like, extract_terms


def test_extract_terms_keeps_chinese_and_latin_tokens():
    terms = extract_terms("一期系统上线 RAG-01")
    assert "一期系统上线 RAG-01" in terms
    assert "RAG-01" in terms
    assert "一期" in terms
    assert "上线" in terms


def test_like_wildcards_are_escaped():
    assert escape_like("100%_ok") == "100\\%\\_ok"
