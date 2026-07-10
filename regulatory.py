"""
Free-text resolution layer — dictionary first, then a persistent cache,
then an LLM fallback, in that order. Every layer costs strictly more
than the one before it, so cheap/instant paths are always tried first:

  dictionary lookup (free, instant, covers ~most real traffic)
    -> disk cache (free after the first time any given input is seen)
      -> LLM call (only for input truly nobody has resolved before)

This exists because the input became free text ("Ireland", "formulary
committee") instead of a closed dropdown — a static dictionary can't
cover the open-ended cases, but paying for an LLM call on every single
request (including the ones the dictionary already handles) would be
wasteful. The grader itself never triggers any of this: resolution
happens exactly once per pipeline run (see pipeline.py), and the
resolved MarketInfo/AudienceInfo gets threaded through to both the
generator and the grader as plain data, not re-derived repeatedly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

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

# Confident-without-an-LLM-call keyword sets. Covers the obvious cases for free;
# only genuinely ambiguous audience text ("formulary committee", "payers") falls
# through to the LLM.
HCP_KEYWORDS = ("hcp", "healthcare professional", "doctor", "physician", "clinician", "nurse", "prescriber")
NON_HCP_KEYWORDS = ("patient", "consumer", "general public", "caregiver", "general audience")

_CACHE_PATH = Path(__file__).parent / "resolution_cache.json"


class MarketInfo(BaseModel):
    market_text: str
    tags: list[str] = []
    body_name: str
    known: bool
    aliases: list[str] = []
    notes: list[str] = []
    source: str  # "dictionary" | "cache" | "llm" | "llm_error" | "unresolved"


class AudienceInfo(BaseModel):
    audience_text: str
    is_hcp: bool
    known: bool
    source: str  # "keyword" | "cache" | "llm" | "llm_error" | "unresolved"
    reasoning: str = ""


# --- cache -------------------------------------------------------------

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass  # cache is a cost optimization, never something a run should fail over


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


# --- market resolution ---------------------------------------------------

_MARKET_LLM_SYSTEM = """You classify a market/country name for pharmaceutical marketing \
compliance purposes. Respond with ONLY a JSON object, no other text, no markdown fences:

{"body_name": "<the applicable pharma advertising regulatory body/code, e.g. 'Health Canada / PAAB'>",
 "tags": ["<short acronym(s) a footer would use, e.g. 'PAAB'>"],
 "notes": ["<0-3 short market-specific compliance notes, e.g. additional-monitoring symbol requirements, DTC advertising rules — only include what you're actually confident about>"],
 "confident": true/false}

Set "confident": false if the input isn't a real, identifiable market/country, or if you \
don't have reasonable confidence in the regulatory body. Never invent a specific law or \
citation you're not sure about — an empty "notes" list is better than a wrong one."""


def _llm_resolve_market(market_text: str, client: Any) -> MarketInfo:
    try:
        raw = client.complete(system=_MARKET_LLM_SYSTEM, user=f"Market/country: {market_text}", max_tokens=300)
        data = _parse_json_response(raw)
        confident = bool(data.get("confident", False))
        return MarketInfo(
            market_text=market_text,
            tags=data.get("tags", []) if confident else [],
            body_name=data.get("body_name") or f"[LLM UNCERTAIN about '{market_text}' — confirm manually]",
            known=confident,
            aliases=[market_text.strip().lower()],
            notes=data.get("notes", []) if confident else [],
            source="llm",
        )
    except Exception as e:
        return MarketInfo(
            market_text=market_text, tags=[],
            body_name=f"[LLM RESOLUTION FAILED for '{market_text}': {type(e).__name__}]",
            known=False, aliases=[market_text.strip().lower()] if market_text else [],
            notes=["LLM-based resolution failed — confirm applicable code manually."],
            source="llm_error",
        )


def resolve_market(market_text: str, client: Optional[Any] = None) -> MarketInfo:
    """
    Dictionary -> cache -> LLM (only if `client` is given), in that order.
    Word-boundary matched, not naive substring (a bare "us" alias would
    otherwise false-positive inside words like "focuses"/"discusses" —
    this was a real bug, caught and fixed once already, see CODE_WALKTHROUGH.md).
    """
    m = (market_text or "").strip().lower()

    for keys, info in MARKET_MAP.items():
        if any(k == m or re.search(rf"\b{re.escape(k)}\b", m) for k in keys):
            return MarketInfo(market_text=market_text, tags=info["tags"], body_name=info["body_name"],
                               known=True, aliases=list(keys), notes=info["notes"], source="dictionary")

    cache = _load_cache()
    cached = cache.get("market", {}).get(m)
    if cached:
        return MarketInfo(**{**cached, "source": "cache"})

    if client is None:
        return MarketInfo(
            market_text=market_text, tags=[],
            body_name=f"[UNRECOGNIZED MARKET: '{market_text}' — confirm applicable code with regulatory/legal]",
            known=False, aliases=[m] if m else [],
            notes=[f"'{market_text}' isn't in MARKET_MAP and no LLM client was passed to "
                   f"resolve_market() to look it up dynamically."],
            source="unresolved",
        )

    result = _llm_resolve_market(market_text, client)
    if result.known:
        cache.setdefault("market", {})[m] = result.model_dump(exclude={"source"})
        _save_cache(cache)
    return result


def market_addendum(market_info: MarketInfo) -> str:
    """
    Builds the market-specific paragraph injected into the USER prompt
    (never the system prompt — see generator.py / llm_client.py for why:
    keeping the system prompt market-agnostic is what lets it stay one
    stable, cacheable prefix across every brand/market/run).
    """
    lines = [f"Applicable regulatory code: {market_info.body_name}."]
    lines.extend(f"- {n}" for n in market_info.notes)
    if not market_info.known:
        lines.append("- Do not guess a specific code — write a generic "
                      "'[CONFIRM APPLICABLE LOCAL CODE]' placeholder in the footer instead.")
    if market_info.source == "llm":
        lines.append("- (Regulatory framework identified via LLM classification, not the "
                      "built-in dictionary — flag this for human confirmation, not just the "
                      "usual monitoring-status checks.)")
    return "\n".join(lines)


# --- audience resolution ---------------------------------------------------

_AUDIENCE_LLM_SYSTEM = """You classify a marketing audience description for pharmaceutical \
compliance purposes: does it refer to licensed healthcare professionals (doctors, nurses, \
pharmacists, prescribers, formulary/P&T committees acting in a clinical-purchasing capacity), \
as opposed to patients, caregivers, or the general public? Respond with ONLY a JSON object, no \
other text, no markdown fences:

{"is_hcp": true/false, "confident": true/false, "reasoning": "<one short sentence>"}

Set "confident": false only if the description is genuinely ambiguous even after your best \
judgment — most real audience descriptions should resolve to true or false confidently."""


def _llm_resolve_audience(audience_text: str, client: Any) -> AudienceInfo:
    try:
        raw = client.complete(system=_AUDIENCE_LLM_SYSTEM, user=f"Audience: {audience_text}", max_tokens=200)
        data = _parse_json_response(raw)
        confident = bool(data.get("confident", False))
        return AudienceInfo(
            audience_text=audience_text,
            is_hcp=bool(data.get("is_hcp", False)) if confident else False,
            known=confident,
            source="llm",
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        return AudienceInfo(
            audience_text=audience_text, is_hcp=False, known=False, source="llm_error",
            reasoning=f"LLM-based resolution failed ({type(e).__name__}) — defaulting to "
                      f"non-HCP (the safer default: it makes audience_tag non-blocking rather "
                      f"than silently skipping a check that should have applied).",
        )


def resolve_audience(audience_text: str, client: Optional[Any] = None) -> AudienceInfo:
    """Keyword match -> cache -> LLM (only if `client` is given), in that order."""
    a = (audience_text or "").strip().lower()

    if any(k in a for k in HCP_KEYWORDS):
        return AudienceInfo(audience_text=audience_text, is_hcp=True, known=True, source="keyword")
    if any(k in a for k in NON_HCP_KEYWORDS):
        return AudienceInfo(audience_text=audience_text, is_hcp=False, known=True, source="keyword")

    cache = _load_cache()
    cached = cache.get("audience", {}).get(a)
    if cached:
        return AudienceInfo(**{**cached, "source": "cache"})

    if client is None:
        return AudienceInfo(
            audience_text=audience_text, is_hcp=False, known=False, source="unresolved",
            reasoning="Ambiguous audience text and no LLM client provided — defaulting to "
                      "non-HCP rather than guessing.",
        )

    result = _llm_resolve_audience(audience_text, client)
    if result.known:
        cache.setdefault("audience", {})[a] = result.model_dump(exclude={"source"})
        _save_cache(cache)
    return result


# Kept for anything that only needs a quick yes/no without the full resolution
# machinery (e.g. schema.py's CampaignBrief.is_hcp() convenience method).
def is_hcp_audience(audience_text: str) -> bool:
    return resolve_audience(audience_text, client=None).is_hcp
