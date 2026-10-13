from app.config import get_settings
from app.graph.routing import route_after_audit, route_after_missing_check, route_after_review


def test_missing_information_goes_to_clarification():
    assert route_after_missing_check({"missing_information": ["项目目标"]}) == "human_clarification"
    assert route_after_missing_check({"missing_information": []}) == "retrieve_evidence"
    assert route_after_missing_check({"status": "failed"}) == "fail"


def test_audit_routes_to_revision_until_limit():
    settings = get_settings()
    original = settings.max_revision_rounds
    settings.max_revision_rounds = 3
    try:
        assert route_after_audit({"audit_report": {"passed": False}, "revision_count": 0}) == "revise_output"
        assert route_after_audit({"audit_report": {"passed": True}, "revision_count": 0}) == "human_approval"
        assert route_after_audit({"audit_report": {"passed": False}, "revision_count": 3}) == "human_approval"
    finally:
        settings.max_revision_rounds = original


def test_review_decision_routing():
    assert route_after_review({"review_decision": {"decision": "approve"}}) == "done"
    assert route_after_review({"review_decision": {"decision": "revise"}}) == "revise_output"
    assert route_after_review({"review_decision": {"decision": "request_information"}}) == "human_clarification"
