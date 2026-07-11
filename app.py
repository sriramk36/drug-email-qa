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
import base64

import streamlit as st
import streamlit.components.v1 as components

from core.schema import CampaignBrief, Channel, EmailType, ContentClassification
from core.llm_client import LLMClient
from pipeline.pipeline_langgraph import build_graph

st.set_page_config(page_title="MLR Draft Pipeline", layout="wide", initial_sidebar_state="expanded")

# --- CSS Overrides ---
st.markdown("""
    <style>
    .st-emotion-cache-1v0mbdj { margin-top: -3rem; }
    .status-card { padding: 1rem; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #ddd; }
    .status-pass { background-color: rgba(0, 200, 0, 0.1); border-left: 5px solid green; }
    .status-fail { background-color: rgba(200, 0, 0, 0.1); border-left: 5px solid red; }
    .status-warn { background-color: rgba(255, 165, 0, 0.1); border-left: 5px solid orange; }
    </style>
""", unsafe_allow_html=True)

st.title("Pharma Marketing Draft Pipeline 🧬")
st.caption(
    "Generates a draft email/web mockup and runs it through a deterministic "
    "compliance-structure grader. Every output is a DRAFT for human MLR review."
)

with st.sidebar:
    st.header("Campaign Configuration")
    
    with st.form("brief_form"):
        channel = st.selectbox("Channel", [c.value for c in Channel], help="Structural switch — changes layout target.")
        email_type = st.selectbox("Email type", [e.value for e in EmailType]) if channel == "email" else None
        
        st.divider()
        market = st.text_input("Market", "UK", help="E.g., UK, US, EU. Unknowns fall back to AI classification.")
        audience = st.text_input("Audience", "HCP", help="E.g., HCP, Patient.")
        brand = st.text_input("Brand", "Dovato", help="Known: Dovato, Nucala, Trelegy, Shingrix.")
        classification = st.selectbox("Classification", [c.value for c in ContentClassification])
        
        st.divider()
        objective = st.text_area("Objective", "Pre-launch HIV treatment awareness", height=80)
        uploaded_files = st.file_uploader("Upload images (optional)", accept_multiple_files=True, type=["png", "jpg", "jpeg", "gif"])
        run_soft = st.checkbox("Run soft review (AI)", value=False, help="Runs 1 extra subjective AI call if structural checks pass.")
        
        submitted = st.form_submit_button("Generate Draft 🚀", use_container_width=True)

if submitted:
    image_map = {}
    if uploaded_files:
        for f in uploaded_files:
            b64 = base64.b64encode(f.read()).decode("utf-8")
            image_map[f.name] = f"data:{f.type};base64,{b64}"

    brief = CampaignBrief(
        channel=channel, email_type=email_type, market=market, audience=audience,
        brand=brand, objective=objective, classification=classification,
        uploaded_images=image_map
    )

    status_box = st.status("🧠 Running LangGraph pipeline...", expanded=True)
    def ui_log(msg):
        status_box.write(msg)

    try:
        client = LLMClient()
    except RuntimeError as e:
        status_box.update(label="Configuration Error", state="error")
        st.error(str(e))
        st.stop()

    t0 = time.time()
    graph = build_graph()
    final_state = {}

    ui_log(f"→ Soft review: {'ON' if run_soft else 'OFF'}")

    for step in graph.stream({
        "brief": brief, "client": client, "run_soft_review": run_soft,
        "iteration": 0, "prev_failed_ids": None,
    }):
        node_name = list(step.keys())[0]
        update = step[node_name]
        final_state.update(update)

        if node_name == "resolve":
            mi, ai = update["market_info"], update["audience_info"]
            ui_log(f"→ [resolve] market → {mi.body_name} (source: **{mi.source}**)")
            ui_log(f"  [resolve] audience → {'HCP' if ai.is_hcp else 'not HCP'} (source: **{ai.source}**)")
        elif node_name == "generate":
            usage = client.last_usage or {}
            kind = "generated" if update["iteration"] == 1 else "revised"
            ui_log(f"→ [generate] draft {kind} (attempt {update['iteration']}) — {usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens")
        elif node_name == "grade":
            report = update["grade_report"]
            ui_log(f"→ [grade] {len(report.items)} rules checked deterministically")
            if update.get("stuck"):
                ui_log("  → Repeated failure detected — stopping iteration early.")
        elif node_name == "soft_review":
            notes = update.get("soft_review_notes", [])
            ui_log(f"→ [soft_review] {len(notes)} advisory note(s)." if notes else "→ [soft_review] no concerns flagged.")

    report = final_state["grade_report"]
    status_box.update(label=f"Done — {final_state['iteration']} iteration(s), {time.time()-t0:.1f}s total",
                       state="complete" if report.all_passed else "error")

    # --- Display Results in Tabs ---
    tab_preview, tab_audit, tab_code = st.tabs(["👁️ Live Preview", "🛡️ Audit & Grades", "💻 Raw Source"])

    html_raw = final_state["html"]
    html_preview = html_raw
    for fname, data_uri in brief.uploaded_images.items():
        html_preview = html_preview.replace(f"uploaded:{fname}", data_uri)

    with tab_preview:
        st.subheader("Rendered HTML Draft")
        if not report.all_passed:
            st.error("⚠️ This draft failed blocking compliance checks. It is NOT ready for distribution.")
        components.html(html_preview, height=800, scrolling=True)
        st.download_button("Download HTML", data=html_preview, file_name=f"{brief.brand}-draft.html", mime="text/html")

    with tab_audit:
        st.subheader(f"Compliance Audit Report (Attempt {final_state['iteration']})")
        
        passed_count = sum(1 for i in report.items if i.passed)
        st.progress(passed_count / len(report.items), text=f"{passed_count} / {len(report.items)} Checks Passed")

        for item in report.items:
            status_class = "status-pass" if item.passed else ("status-warn" if item.severity == "warning" else "status-fail")
            icon = "✅" if item.passed else ("⚠️" if item.severity == "warning" else "❌")
            st.markdown(f"""
            <div class="status-card {status_class}">
                <strong>{icon} {item.label}</strong><br/>
                <span style="font-size: 0.9em; color: #555;">{item.detail}</span>
            </div>
            """, unsafe_allow_html=True)

        notes = final_state.get("soft_review_notes", [])
        if notes:
            st.subheader("Soft Review Advisory (AI)")
            for n in notes:
                st.info(f"**{n.concern}** — {n.detail}")
    
    with tab_code:
        st.subheader("Raw Generated Code")
        st.code(html_raw, language="html")
