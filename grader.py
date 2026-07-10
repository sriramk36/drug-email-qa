"""
Grader — Loop 2 (verification loop) in loop-engineering terms.

Deliberately NOT an LLM call for the blocking rules. Structural
compliance checks (is the AE box there, is the audience tag there, did
the brand name leak into unbranded copy) are things regex/DOM parsing
can check exactly and reproducibly. Saving the LLM for judgment calls
keeps the audit trail auditable — a human reviewer can see precisely
why something failed, not just an LLM's opinion that it failed.

IMPORTANT: market/audience resolution (regulatory.py) can now involve
an LLM call for genuinely unrecognized free-text input. That call
happens exactly ONCE per pipeline run, upstream, in pipeline.py — not
here. Rules receive the already-resolved MarketInfo/AudienceInfo as
plain data via GradingContext. This keeps the grader's core guarantee
intact: grading itself never makes a network call, regardless of how
the inputs it's checking against were resolved.

Every rule function has the same signature:
    (soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from bs4 import BeautifulSoup

from schema import CampaignBrief, GradeItem, GradeReport, ContentClassification
from regulatory import MarketInfo, AudienceInfo


@dataclass
class GradingContext:
    tokens: dict
    market_info: MarketInfo
    audience_info: AudienceInfo


def _visible_body_text(soup: BeautifulSoup) -> str:
    """
    Text a recipient would actually see in the 600px email render —
    excludes the annotation/audit footer, which is allowed to mention
    the brand name internally for the production team.
    """
    body = soup.select_one(".email-content") or soup.select_one(".email-outer") or soup
    for ann in body.select(".annotation-wrap"):
        ann.decompose()
    return body.get_text(" ", strip=True)


def rule_draft_watermark(soup, raw_html, brief, ctx) -> GradeItem:
    ok = "DRAFT" in raw_html and "Not approved for distribution" in raw_html
    return GradeItem(
        rule_id="watermark",
        label="DRAFT watermark present",
        passed=ok,
        detail="Found DRAFT / not-approved-for-distribution watermark." if ok
        else "Missing the DRAFT — Not approved for distribution watermark.",
    )


def rule_job_code_pending(soup, raw_html, brief, ctx) -> GradeItem:
    ok = "[CL ID" in raw_html or "CL ID — PENDING" in raw_html
    return GradeItem(
        rule_id="job_code",
        label="Job code placeholder present",
        passed=ok,
        detail="Job code placeholder found." if ok else "No [CL ID — PENDING] placeholder found in footer.",
    )


def rule_hcp_audience_tag(soup, raw_html, brief, ctx) -> GradeItem:
    if not ctx.audience_info.is_hcp:
        note = "" if ctx.audience_info.known else " (resolver was uncertain — treated as not-HCP by default)"
        return GradeItem(rule_id="audience_tag", label="HCP-only audience statement",
                          passed=True, detail=f"Not required — audience '{brief.audience}' wasn't recognized as HCP{note}.",
                          severity="warning")
    text = _visible_body_text(soup).lower()
    market_info = ctx.market_info
    # If the market itself wasn't recognized we can't require a market word to appear at
    # all — just require the HCP-only statement itself, and flag the market as unverified.
    # If it *was* recognized, accept any known synonym ("UK" satisfies "United Kingdom").
    ok = "healthcare professional" in text
    if market_info.known:
        # Word-boundary match, not naive substring — a bare "us" alias would
        # otherwise false-positive inside words like "focuses"/"discusses".
        ok = ok and any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in market_info.aliases)
    return GradeItem(
        rule_id="audience_tag",
        label="HCP-only audience statement",
        passed=ok,
        detail="Explicit HCP-only audience line found in body copy." if ok
        else f"Body copy does not clearly state this is for {brief.market} healthcare professionals only.",
    )


def rule_ae_box(soup, raw_html, brief, ctx) -> GradeItem:
    candidates = soup.find_all(style=re.compile(r"border\s*:\s*\d"))
    has_border_el = len(candidates) > 0 or "border: 2px" in raw_html or "2px solid" in raw_html
    ae_line = ctx.tokens.get("ae_report_line", "")
    has_ae_text = "adverse event" in raw_html.lower()
    line_matches = ae_line[:20].lower() in raw_html.lower() if ae_line else False
    ok = has_border_el and has_ae_text and line_matches
    detail_bits = []
    if not has_border_el:
        detail_bits.append("no visibly bordered element detected")
    if not has_ae_text:
        detail_bits.append("no 'adverse event' text found")
    if not line_matches:
        detail_bits.append("AE reporting line doesn't match the brand's required wording")
    return GradeItem(
        rule_id="ae_box",
        label="AE reporting box (bordered, correct wording)",
        passed=ok,
        detail="Bordered AE box with correct reporting line present." if ok else "; ".join(detail_bits),
    )


def rule_brand_leak(soup, raw_html, brief, ctx) -> GradeItem:
    if brief.classification != ContentClassification.UNBRANDED_DISEASE_AWARENESS:
        return GradeItem(rule_id="brand_leak", label="No product name in unbranded body copy",
                          passed=True, detail="Not applicable — content is branded.", severity="warning")
    text = _visible_body_text(soup)
    pattern = re.compile(re.escape(brief.brand), re.IGNORECASE)
    hits = pattern.findall(text)
    ok = len(hits) == 0
    return GradeItem(
        rule_id="brand_leak",
        label="No product name in unbranded body copy",
        passed=ok,
        detail="Product name does not appear in visible body copy." if ok
        else f"Product name '{brief.brand}' appears {len(hits)}x in visible body copy — must be removed for unbranded disease-awareness content.",
    )


def rule_pi_link_if_branded(soup, raw_html, brief, ctx) -> GradeItem:
    if brief.classification != ContentClassification.BRANDED:
        return GradeItem(rule_id="pi_link", label="Prescribing Information link placeholder present",
                          passed=True, detail="Not applicable — content is unbranded.", severity="warning")
    ok = "Prescribing Information" in raw_html
    return GradeItem(
        rule_id="pi_link",
        label="Prescribing Information link placeholder present",
        passed=ok,
        detail="PI link/placeholder present." if ok else "Branded content is missing a Prescribing Information link/placeholder.",
    )


def rule_regulatory_footer_tag(soup, raw_html, brief, ctx) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known:
        source_note = f" (resolver source: {market_info.source})"
        return GradeItem(
            rule_id="reg_footer",
            label="Regulatory code referenced in footer",
            passed=False,
            detail=f"Market '{brief.market}' couldn't be confidently resolved{source_note} — "
                   f"confirm the applicable code manually.",
            severity="warning",
        )
    expected = market_info.tags
    ok = any(tag in raw_html for tag in expected)
    source_note = "" if market_info.source == "dictionary" else f" [resolved via {market_info.source} — double-check this]"
    return GradeItem(
        rule_id="reg_footer",
        label="Regulatory code referenced in footer",
        passed=ok,
        detail=(f"Found {market_info.body_name} reference.{source_note}" if ok
                else f"Footer does not reference the applicable code ({'/'.join(expected)}).{source_note}"),
    )


def rule_no_hardcoded_cta_url(soup, raw_html, brief, ctx) -> GradeItem:
    real_links = [a.get("href", "") for a in soup.find_all("a")]
    bad = [h for h in real_links if h and h not in ("#",) and not h.startswith("#")
           and "TBC" not in h and "pending" not in h.lower()]
    ok = len(bad) == 0
    return GradeItem(
        rule_id="cta_url",
        label="CTA links are placeholders, not invented URLs",
        passed=ok,
        detail="All CTAs are placeholder links." if ok
        else f"Found {len(bad)} link(s) pointing to a real-looking, non-placeholder URL: {bad[:3]}",
    )


def rule_logo_not_embedded(soup, raw_html, brief, ctx) -> GradeItem:
    imgs = soup.find_all("img")
    real_logo_imgs = [i for i in imgs if i.get("src") and not i.get("src", "").startswith(("placeholder", "#"))
                       and "logo" in " ".join(i.get("class", [])).lower()]
    ok = len(real_logo_imgs) == 0
    return GradeItem(
        rule_id="logo_placeholder",
        label="Logo rendered as labeled placeholder, not a real embedded image",
        passed=ok,
        detail="No real logo image embedded — placeholder slot used." if ok
        else "An <img> with a real src is being used for a logo slot; this must stay a placeholder in a draft.",
    )


# --- Market-specific rules -------------------------------------------------
# The actual answer to "EU rules are different from US rules, right?" — separate
# from the tag-swap in rule_regulatory_footer_tag because the *content* differs
# by market, not just which acronym appears. Both are deliberately "warning"
# severity, never blocking: the tool has no way to know a product's real
# additional-monitoring or Boxed Warning status, so it can only remind a human
# to confirm — asserting either as a pass/fail would be claiming certainty the
# tool doesn't have.

def rule_black_triangle_uk_eu(soup, raw_html, brief, ctx) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known or not any(t in market_info.tags for t in ("ABPI", "EFPIA")):
        return GradeItem(rule_id="black_triangle", label="Black triangle / additional-monitoring reminder (UK/EU)",
                          passed=True, detail="Not applicable — market isn't UK/EU.", severity="warning")
    mentioned = "▼" in raw_html or "additional monitoring" in raw_html.lower()
    return GradeItem(
        rule_id="black_triangle",
        label="Black triangle / additional-monitoring reminder (UK/EU)",
        passed=mentioned,
        detail="Draft references additional-monitoring status." if mentioned
        else f"UK/EU draft for '{brief.brand}' doesn't mention additional-monitoring status — "
             f"confirm with regulatory whether the ▼ symbol is required before this ships.",
        severity="warning",
    )


def rule_boxed_warning_us(soup, raw_html, brief, ctx) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known or "FDA" not in market_info.tags:
        return GradeItem(rule_id="boxed_warning", label="Boxed Warning reminder (US)",
                          passed=True, detail="Not applicable — market isn't US.", severity="warning")
    mentioned = "boxed warning" in raw_html.lower()
    return GradeItem(
        rule_id="boxed_warning",
        label="Boxed Warning reminder (US)",
        passed=mentioned,
        detail="Draft references Boxed Warning status." if mentioned
        else f"US draft for '{brief.brand}' doesn't mention Boxed Warning status — "
             f"confirm with regulatory whether one applies before this ships.",
        severity="warning",
    )


ALL_RULES = [
    rule_draft_watermark,
    rule_job_code_pending,
    rule_hcp_audience_tag,
    rule_ae_box,
    rule_brand_leak,
    rule_pi_link_if_branded,
    rule_regulatory_footer_tag,
    rule_no_hardcoded_cta_url,
    rule_logo_not_embedded,
    rule_black_triangle_uk_eu,
    rule_boxed_warning_us,
]


def grade(html: str, brief: CampaignBrief, ctx: GradingContext, iteration: int) -> GradeReport:
    soup = BeautifulSoup(html, "html.parser")
    items = [rule(soup, html, brief, ctx) for rule in ALL_RULES]
    return GradeReport(items=items, iteration=iteration)
