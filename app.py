"""
Streamlit UI — runs on pipeline_langgraph.py's graph, not the plain
pipeline.py loop. Uses graph.stream() to get a live update after every
node (resolve / generate / grade / soft_review) with zero manual
ui_log() plumbing inside the loop logic itself — that per-step
visibility is what LangGraph gives you for free versus the plain
version, and this file is where that actually gets used, not just
demonstrated in a CLI print statement.

Run with: streamlit run app.py
"""

import time

import streamlit as st
import streamlit.components.v1 as components

from core.schema import CampaignBrief, Channel, EmailType, ContentClassification
from core.llm_client import LLMClient
from pipeline.pipeline_langgraph import build_graph

st.set_page_config(page_title="MLR Draft Pipeline (LangGraph)", layout="wide")

st.title("Pharma Marketing Draft Pipeline — prototype (LangGraph)")
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
                                     "Anything else (e.g. 'Ireland') triggers ONE AI classification call, "
                                     "cached to disk so the same market never pays for a second call.")
    with col2:
        audience = st.text_input("Audience", "HCP",
                                  help="Free text. Obvious HCP/patient keywords resolve for free. Genuinely "
                                       "ambiguous phrasing (e.g. 'formulary committee') falls back to one "
                                       "cached AI call, same as market.")
        brand = st.text_input("Brand", "Dovato",
                               help="Free text. Known tokens: Dovato, Nucala, Trelegy, Shingrix. "
                                    "Unknown brands fall back to placeholder tokens rather than guessing real values.")
        classification = st.selectbox(
            "Classification",
            [c.value for c in ContentClassification],
            help="Kept as a toggle, not free text — this decides whether the brand name is "
                 "allowed in body copy at all, so it drives real branching logic, not just display text.",
        )
    with col3:
        objective = st.text_area("Objective", "Pre-launch HIV treatment awareness", height=120)
        uploaded_files = st.file_uploader("Upload images (optional)", accept_multiple_files=True, type=["png", "jpg", "jpeg", "gif"])
        run_soft = st.checkbox(
            "Run soft review",
            value=False,
            help="OPTIONAL — costs 1 extra AI call, only spent if all 11 blocking checks already pass. "
                 "Checks subjective things (implied claims, fair-balance tone) that no rule can. "
                 "Off by default so nothing costs extra unless you ask for it.",
        )

    submitted = st.form_submit_button("Generate draft (live, LangGraph)")

if submitted:
    import base64
    image_map = {}
    uploaded_names = []
    if uploaded_files:
        for f in uploaded_files:
            b64 = base64.b64encode(f.read()).decode("utf-8")
            image_map[f.name] = f"data:{f.type};base64,{b64}"
            uploaded_names.append(f.name)

    brief = CampaignBrief(
        channel=channel, email_type=email_type, market=market, audience=audience,
        brand=brand, objective=objective, classification=classification,
        uploaded_images=image_map
    )

    status_box = st.status("Running LangGraph pipeline...", expanded=True)
    def ui_log(msg):
        status_box.write(msg)

    try:
        client = LLMClient()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    t0 = time.time()
    graph = build_graph()
    final_state = {}

    ui_log(f"→ Soft review: {'ON (will run 1 extra call if all checks pass)' if run_soft else 'OFF (default — no extra call)'}")

    for step in graph.stream({
        "brief": brief, "client": client, "run_soft_review": run_soft,
        "iteration": 0, "prev_failed_ids": None,
    }):
        node_name = list(step.keys())[0]
        update = step[node_name]
        final_state.update(update)

        if node_name == "resolve":
            mi, ai = update["market_info"], update["audience_info"]
            ui_log(f"→ [resolve] market → {mi.body_name} (source: **{mi.source}**"
                   f"{', free' if mi.source in ('dictionary','cache') else ', 1 AI call — now cached'})")
            ui_log(f"  [resolve] audience → {'HCP' if ai.is_hcp else 'not HCP'} (source: **{ai.source}**"
                   f"{', free' if ai.source in ('keyword','cache') else ', 1 AI call — now cached'})")

        elif node_name == "generate":
            usage = client.last_usage or {}
            notes = []
            if usage.get("cache_read_input_tokens"):
                notes.append(f"cache hit: {usage['cache_read_input_tokens']} tokens (cheaper, exact discount per Azure's pricing)")
            if usage.get("reasoning_tokens"):
                notes.append(f"reasoning tokens: {usage['reasoning_tokens']} (hidden thinking, not visible output)")
            cache_note = f" — {', '.join(notes)}" if notes else ""
            kind = "generated" if update["iteration"] == 1 else "revised"
            ui_log(f"→ [generate] draft {kind} (attempt {update['iteration']}) — "
                   f"{usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens{cache_note}")

        elif node_name == "grade":
            report = update["grade_report"]
            ui_log(f"→ [grade] {len(report.items)} rules checked, deterministic, no AI call")
            for item in report.items:
                ui_log(f"  {'✅' if item.passed else '❌'} {item.label} — {item.detail}")
            if update.get("stuck"):
                ui_log("  → same check(s) failed two attempts in a row — stopping instead of "
                        "burning a 3rd identical call.")

        elif node_name == "soft_review":
            notes = update.get("soft_review_notes", [])
            if run_soft and final_state["grade_report"].all_passed:
                ui_log(f"→ [soft_review] {len(notes)} advisory note(s)." if notes else "→ [soft_review] no concerns flagged.")
            else:
                ui_log("→ [soft_review] skipped (off, or blocking checks not all passed yet).")

    report = final_state["grade_report"]
    status_box.update(label=f"Done — {final_state['iteration']} iteration(s), {time.time()-t0:.1f}s total",
                       state="complete" if report.all_passed else "error")

    st.subheader("Audit trail (deterministic — zero AI calls in this step)")
    st.write(f"Iterations used: **{final_state['iteration']}** / 3")
    for item in report.items:
        icon = "✅" if item.passed else "❌"
        sev = "" if item.severity == "blocking" else " *(warning, non-blocking)*"
        st.write(f"{icon} **{item.label}**{sev} — {item.detail}")

    if report.all_passed:
        st.success("All blocking checks passed. Still requires human MLR review before any use.")
    else:
        st.warning(f"Still failing after {final_state['iteration']} iterations — needs manual fixing.")

    notes = final_state.get("soft_review_notes", [])
    if notes:
        st.subheader("Soft review — advisory only, a second AI's opinion, not a verified finding")
        for n in notes:
            st.info(f"**{n.concern}** — {n.detail}")

    html = final_state["html"]
    
    # Inject base64 images into HTML replacing the placeholders
    for fname, data_uri in brief.uploaded_images.items():
        html = html.replace(f"uploaded:{fname}", data_uri)
    
    st.subheader("Rendered draft")
    components.html(html, height=900, scrolling=True)

    st.download_button(
        "Download HTML",
        data=html,
        file_name=f"{brief.brand}-{brief.market}-draft.html",
        mime="text/html",
    )
