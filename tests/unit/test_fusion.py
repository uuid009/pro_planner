from app.rag.fusion import reciprocal_rank_fusion


def test_rrf_promotes_items_that_rank_well_in_both_lists():
    lexical = ["a", "b", "c"]
    semantic = ["b", "d", "a"]
    fused = reciprocal_rank_fusion([lexical, semantic], k=60)
    assert [item_id for item_id, _score in fused][:2] == ["b", "a"]
    scores = dict(fused)
    assert scores["b"] > scores["a"] > scores["c"]
    assert scores["b"] > scores["d"]


def test_rrf_keeps_unique_candidates():
    fused = reciprocal_rank_fusion([["only-lexical"], ["only-vector"]])
    assert {item_id for item_id, _score in fused} == {"only-lexical", "only-vector"}
