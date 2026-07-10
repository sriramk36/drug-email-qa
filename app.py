"""
Minimal Streamlit UI. Run with: streamlit run app.py

This is intentionally thin — the interesting logic lives in
generator.py / grader.py / regulatory.py / soft_review.py / pipeline.py
so it stays testable outside a browser too. This file inlines the same
loop pipeline.py's run_pipeline() runs, rather than calling it directly,
so it can push a UI log line after every individual step instead of
only showing a result at the end.
"""

import time

import streamlit as st
import streamlit.components.v1 as components

from schema import CampaignBrief, Channel, EmailType, ContentClassification
from brand_config import get_brand_tokens
from generator import generate, revise
from grader import grade, GradingContext
from llm_client import LLMClient
from regulatory import resolve_market, resolve_audience
from soft_review import soft_review
from trace_logger import log_iteration, log_resolution

st.set_page_config(page_title="MLR Draft Pipeline (prototype)", layout="wide")

st.title("Pharma Marketing Draft Pipeline — prototype")
st.caption(
    "Generates a draft email/web mockup and runs it through a deterministic "
    "compliance-structure grader. Every output is a DRAFT for human MLR review — "
    "this tool does not and cannot approve content for distribution."
)

with st.form("brief_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        channel = st.selectbox("Channel", [c.value for c in Channel],
                                help="Structural switch — changes which layout the generator targets.")
        email_type = st.selectbox("Email type", [e.value for e in EmailType]) if channel == "email" else None
        market = st.text_input("Market", "UK",
                                help="Free text. UK/US/EU/Swiss resolve instantly for free via a dictionary. "
                                     "Anything else (e.g. 'Ireland') triggers ONE LLM classification call, "
                                     "cached to disk so the same market never pays for a second call.")
    with col2:
        audience = st.text_input("Audience", "HCP",
                                  help="Free text. Obvious HCP/patient keywords resolve for free. Genuinely "
                                       "ambiguous phrasing (e.g. 'formulary committee') falls back to one "
                                       "cached LLM call, same as market.")
        brand = st.text_input("Brand", "Dovato",
                               help="Free text. Known tokens: Dovato, Nucala, Trelegy, Shingrix. "
                                    "Unknown brands fall back to placeholder tokens (see brand_config.py) "
                                    "rather than guessing real values.")
        classification = st.selectbox(
            "Classification",
            [c.value for c in ContentClassification],
            help="Kept as a toggle, not free text — this decides whether the brand name is "
                 "allowed in body copy at all, so it drives real branching logic, not just display text.",
        )
    with col3:
        objective = st.text_area("Objective", "Pre-launch HIV treatment awareness", height=120)
        run_soft = st.checkbox("Run soft review (1 extra LLM call, only if all blocking checks pass)", value=True)

    submitted = st.form_submit_button("Generate draft (live)")

if submitted:
    brief = CampaignBrief(
        channel=channel, email_type=email_type, market=market, audience=audience,
        brand=brand, objective=objective, classification=classification,
    )

    status_box = st.status("Running pipeline...", expanded=True)
    def ui_log(msg):
        status_box.write(msg)

    try:
        client = LLMClient()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    t0 = time.time()

    # --- resolve once, up front ---
    ui_log(f"→ [1/4] Resolving market '{brief.market}' and audience '{brief.audience}'...")
    market_info = resolve_market(brief.market, client=client)
    audience_info = resolve_audience(brief.audience, client=client)
    log_resolution(brief, market_info, audience_info)
    ui_log(f"  market: {market_info.body_name} (source: **{market_info.source}**"
           f"{', cost: free' if market_info.source in ('dictionary','cache') else ', cost: 1 LLM call, now cached'})")
    ui_log(f"  audience: {'HCP' if audience_info.is_hcp else 'not HCP'} (source: **{audience_info.source}**"
           f"{', cost: free' if audience_info.source in ('keyword','cache') else ', cost: 1 LLM call, now cached'})")

    ctx = GradingContext(tokens=get_brand_tokens(brief.brand), market_info=market_info, audience_info=audience_info)

    # --- generate ---
    ui_log(f"→ [2/4] Calling generator (attempt 1)...")
    html = generate(brief, client, ctx)
    usage = client.last_usage or {}
    cache_note = ""
    if usage.get("cache_read_input_tokens"):
        cache_note = f" — cache HIT: {usage['cache_read_input_tokens']} tokens read at ~10% cost"
    elif usage.get("cache_creation_input_tokens"):
        cache_note = f" — cache WRITE: {usage['cache_creation_input_tokens']} tokens (first call, pays 1.25x once)"
    ui_log(f"✓ Draft received in {time.time()-t0:.1f}s ({len(html)} chars, "
           f"{usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens{cache_note})")

    # --- grade (deterministic, zero LLM calls regardless of how market/audience were resolved above) ---
    iteration = 1
    prev_failed_ids = None
    ui_log(f"→ [3/4] Grading {len(grade(html, brief, ctx, 1).items)} rules (deterministic)...")
    report = grade(html, brief, ctx, iteration=iteration)
    log_iteration(brief, report, iteration=iteration)
    for item in report.items:
        ui_log(f"  {'✅' if item.passed else '❌'} {item.label} — {item.detail}")

    while not report.all_passed and iteration < 3:
        current_failed_ids = tuple(sorted(i.rule_id for i in report.failed_items))
        if iteration > 1 and current_failed_ids == prev_failed_ids:
            ui_log(f"→ Same check(s) failed two attempts in a row — stopping instead of burning a "
                   f"3rd identical call. Fix the prompt, don't just retry.")
            break
        prev_failed_ids = current_failed_ids

        iteration += 1
        failed = report.failed_items
        ui_log(f"→ {len(failed)} check(s) failed — revising (attempt {iteration}) with specific failures...")
        t1 = time.time()
        html = revise(brief, html, report, client, ctx)
        usage = client.last_usage or {}
        cache_note = f" — cache read: {usage.get('cache_read_input_tokens', 0)} tokens" if usage.get("cache_read_input_tokens") else ""
        ui_log(f"✓ Revision received in {time.time()-t1:.1f}s "
               f"({usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out{cache_note})")
        ui_log(f"→ Re-grading...")
        report = grade(html, brief, ctx, iteration=iteration)
        log_iteration(brief, report, iteration=iteration)
        for item in report.items:
            ui_log(f"  {'✅' if item.passed else '❌'} {item.label} — {item.detail}")

    # --- soft review: the genuinely agentic step, and the only optional/skippable one ---
    notes = []
    if run_soft and report.all_passed:
        ui_log("→ [4/4] All blocking checks passed — running soft review (advisory, 1 LLM call)...")
        notes = soft_review(html, brief, client)
        ui_log(f"  {len(notes)} advisory note(s)." if notes else "  No concerns flagged.")
    elif run_soft:
        ui_log("→ [4/4] Skipping soft review — blocking checks didn't all pass, nothing advisory to add yet.")
    else:
        ui_log("→ [4/4] Soft review skipped (unchecked).")

    status_box.update(label=f"Done — {iteration} iteration(s), {time.time()-t0:.1f}s total",
                       state="complete" if report.all_passed else "error")

    st.subheader("Audit trail (deterministic — zero LLM calls in this step)")
    st.write(f"Iterations used: **{iteration}** / 3")
    for item in report.items:
        icon = "✅" if item.passed else "❌"
        sev = "" if item.severity == "blocking" else " *(warning, non-blocking)*"
        st.write(f"{icon} **{item.label}**{sev} — {item.detail}")

    if report.all_passed:
        st.success("All blocking checks passed. Still requires human MLR review before any use.")
    else:
        st.warning(f"Still failing after {iteration} iterations — needs manual fixing.")

    if notes:
        st.subheader("Soft review — advisory only, a second AI's opinion, not a verified finding")
        for n in notes:
            st.info(f"**{n.concern}** — {n.detail}")

    st.subheader("Rendered draft")
    components.html(html, height=900, scrolling=True)

    st.download_button(
        "Download HTML",
        data=html,
        file_name=f"{brief.brand}-{brief.market}-draft.html",
        mime="text/html",
    )
