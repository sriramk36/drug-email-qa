"""
Free-text resolution layer.

Once market/audience/brand became plain text inputs instead of dropdowns,
the grader can no longer assume `brief.market == "UK"` will match exactly.
This module is the one place that turns messy human input ("United
Kingdom", "uk", "Britain") into the regulatory tags the grader checks
for, with an honest fallback for anything it doesn't recognize.
"""

from __future__ import annotations

import re

MARKET_MAP = {
    ("uk", "united kingdom", "britain", "gb", "england"): {
        "tags": ["ABPI"], "body_name": "ABPI Code of Practice",
        "notes": [
            "If this product is newly authorized or under additional monitoring, UK "
            "promotional material must display the black triangle (▼) symbol per the "
            "MHRA's Black Triangle Scheme — confirm the product's current monitoring "
            "status with regulatory before removing this.",
        ],
    },
    ("us", "usa", "united states", "america"): {
        "tags": ["FDA", "OPDP"], "body_name": "FDA / OPDP",
        "notes": [
            "If this product carries an FDA Boxed Warning, it must be prominently "
            "displayed near the safety information, not just linked — confirm with "
            "regulatory whether a Boxed Warning applies.",
            "US rules permit direct-to-consumer promotion (unlike UK/EU) but require "
            "the same fair-balance standard: risks get comparable prominence to benefits.",
        ],
    },
    ("eu", "europe", "european union"): {
        "tags": ["EFPIA"], "body_name": "EFPIA Code",
        "notes": [
            "If this product is newly authorized or under additional monitoring, EU "
            "promotional material must display the black triangle (▼) symbol per EMA "
            "pharmacovigilance rules — confirm current monitoring status with regulatory.",
            "Most EU member states prohibit direct-to-consumer prescription drug "
            "advertising — confirm this campaign is HCP-directed, not patient-facing, "
            "before using EFPIA rather than a stricter local consumer-protection code.",
        ],
    },
    ("swiss", "switzerland"): {
        "tags": ["Swissmedic", "Pharma Code"], "body_name": "Swissmedic / Pharma Code",
        "notes": [
            "Switzerland is not an EU member — Swissmedic rules apply, not EMA/EFPIA. "
            "Confirm this wasn't defaulted to EU guidance by mistake.",
        ],
    },
}

HCP_KEYWORDS = ("hcp", "healthcare professional", "doctor", "physician", "clinician", "nurse", "prescriber")


def resolve_market(market_text: str) -> dict:
    """
    Returns {"tags": [...], "body_name": str, "known": bool, "aliases": [...]}.
    Unknown markets get an honest "known": False rather than a guess —
    the grader turns this into a warning, not a silent pass.

    "aliases" matters because free text means what the user typed
    ("United Kingdom") won't necessarily match what the generated copy
    says ("UK") — the grader should accept any recognized synonym, not
    just the literal input string.
    """
    m = (market_text or "").strip().lower()
    for keys, info in MARKET_MAP.items():
        if any(k == m or re.search(rf"\b{re.escape(k)}\b", m) for k in keys):
            return {**info, "known": True, "aliases": list(keys)}
    return {
        "tags": [],
        "body_name": f"[UNRECOGNIZED MARKET: '{market_text}' — confirm applicable code with regulatory/legal]",
        "known": False,
        "aliases": [market_text.strip().lower()] if market_text else [],
        "notes": [f"'{market_text}' isn't in MARKET_MAP — add it there with the correct regulatory "
                  f"body and any market-specific notes (e.g. black triangle / DTC rules) rather than "
                  f"guessing here."],
    }


def market_addendum(market_text: str) -> str:
    """
    Builds the market-specific paragraph injected into the USER prompt
    (never the system prompt — see generator.py / llm_client.py for why:
    keeping the system prompt market-agnostic is what lets it stay one
    stable, cacheable prefix across every brand/market/run instead of
    only within a single run).
    """
    info = resolve_market(market_text)
    lines = [f"Applicable regulatory code: {info['body_name']}."]
    lines.extend(f"- {n}" for n in info.get("notes", []))
    if not info["known"]:
        lines.append("- Do not guess a specific code — write a generic "
                      "'[CONFIRM APPLICABLE LOCAL CODE]' placeholder in the footer instead.")
    return "\n".join(lines)


def is_hcp_audience(audience_text: str) -> bool:
    a = (audience_text or "").strip().lower()
    return any(k in a for k in HCP_KEYWORDS)
