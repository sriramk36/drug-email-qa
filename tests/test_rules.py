from knowledge.context import build_context
from knowledge.rules import build_review_rules


def test_rules_extract_banned_claims_from_brand_guidelines():
    context = build_context({"drug": "NovaMed", "audience": "Adults", "goal": "Awareness", "message": "Test"})
    rules = build_review_rules(context)
    assert "cure" in rules["banned_claims"]
    assert "buy now" in rules["promotional_phrases"]
    assert "learn more" in rules["educational_phrases"]


def test_rules_extract_compliance_keywords():
    context = build_context({"drug": "NovaMed", "audience": "Adults", "goal": "Awareness", "message": "Test"})
    rules = build_review_rules(context)
    assert "safety" in rules["compliance_keywords"]
    assert "disclaimer" in rules["compliance_keywords"]
