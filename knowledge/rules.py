"""Extract review rules from knowledge-base markdown loaded into context."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _extract_quoted_phrases(text: str) -> List[str]:
    return [m.group(1) or m.group(2) for m in re.finditer(r"'([^']+)'|\"([^\"]+)\"", text or "")]


def build_review_rules(context: Dict[str, Any]) -> Dict[str, Any]:
    brand = context.get("brand_guidelines", "")
    email = context.get("email_guidelines", "")
    compliance = context.get("compliance_rules", "")
    brand_lower = brand.lower()
    compliance_lower = compliance.lower()

    quoted_brand = [p.lower() for p in _extract_quoted_phrases(brand)]
    promotional = [p for p in quoted_brand if "buy" in p or "act now" in p]
    if not promotional:
        promotional = ["buy now", "act now"]

    educational = [p for p in quoted_brand if "learn" in p or "speak" in p]
    if not educational:
        educational = ["learn more", "speak with"]

    banned_from_brand = [p for p in quoted_brand if any(t in p for t in ("miracle", "cure", "guarantee"))]
    banned_claims = list(dict.fromkeys(
        banned_from_brand + ["cure", "guarantee", "prevent", "eliminate", "miracle", "instant"]
    ))

    compliance_keywords: List[str] = []
    if "safety" in compliance_lower:
        compliance_keywords.append("safety")
    if "disclaimer" in compliance_lower:
        compliance_keywords.append("disclaimer")

    max_words = 220
    if "concise" in email.lower():
        max_words = 220

    return {
        "banned_claims": banned_claims,
        "promotional_phrases": promotional,
        "educational_phrases": educational,
        "compliance_keywords": compliance_keywords,
        "requires_subject": "subject" in email.lower(),
        "requires_body": "body" in email.lower(),
        "requires_cta": "cta" in email.lower(),
        "requires_professional_guidance": "professional guidance" in email.lower() or "professional" in email.lower(),
        "max_words": max_words,
    }
