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

from core.schema import CampaignBrief, Channel, EmailType, ContentClassification, Severity
from core.llm_client import LLMClient
from pipeline.pipeline_langgraph import build_graph

st.set_page_config(
    page_title="MLR Draft Pipeline",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Premium Dark-Mode CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ═══════════════════════════════════════════════
       Base Typography & Colors
       ═══════════════════════════════════════════════ */
    :root {
        --bg-primary:    #0f1117;
        --bg-secondary:  #161b22;
        --bg-card:       rgba(255, 255, 255, 0.03);
        --border-subtle: rgba(255, 255, 255, 0.08);
        --text-primary:  #e6edf3;
        --text-muted:    #8b949e;
        --accent-indigo: #6366f1;
        --accent-purple: #a855f7;
        --accent-emerald:#10b981;
        --accent-rose:   #f43f5e;
        --accent-amber:  #f59e0b;
        --accent-sky:    #38bdf8;
        --gradient-main: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* ═══════════════════════════════════════════════
       Header Area
       ═══════════════════════════════════════════════ */
    .hero-header {
        background: linear-gradient(135deg, rgba(99,102,241,0.12) 0%, rgba(168,85,247,0.08) 50%, rgba(236,72,153,0.06) 100%);
        border: 1px solid rgba(99,102,241,0.2);
        border-radius: 16px;
        padding: 2rem 2.5rem;
        margin-bottom: 1.5rem;
        position: relative;
        overflow: hidden;
    }
    .hero-header::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -20%;
        width: 300px;
        height: 300px;
        background: radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%);
        border-radius: 50%;
        pointer-events: none;
    }
    .hero-header h1 {
        font-size: 1.85rem;
        font-weight: 800;
        background: var(--gradient-main);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 0 0.3rem 0;
        letter-spacing: -0.02em;
    }
    .hero-header p {
        color: var(--text-muted);
        font-size: 0.92rem;
        margin: 0;
        line-height: 1.5;
    }

    /* ═══════════════════════════════════════════════
       Status Cards (Audit Results)
       ═══════════════════════════════════════════════ */
    .status-card {
        padding: 1rem 1.25rem;
        border-radius: 12px;
        margin-bottom: 0.75rem;
        background: var(--bg-card);
        backdrop-filter: blur(12px);
        border: 1px solid var(--border-subtle);
        transition: transform 0.2s cubic-bezier(0.4,0,0.2,1),
                    box-shadow 0.2s cubic-bezier(0.4,0,0.2,1),
                    border-color 0.2s ease;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        color: var(--text-primary);
    }
    .status-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        border-color: rgba(255,255,255,0.12);
    }
    .status-card strong {
        font-weight: 600;
        font-size: 0.95rem;
    }

    .status-pass {
        border-left: 4px solid var(--accent-emerald);
        background: linear-gradient(90deg, rgba(16,185,129,0.08) 0%, transparent 40%);
    }
    .status-fail {
        border-left: 4px solid var(--accent-rose);
        background: linear-gradient(90deg, rgba(244,63,94,0.08) 0%, transparent 40%);
    }
    .status-warn {
        border-left: 4px solid var(--accent-amber);
        background: linear-gradient(90deg, rgba(245,158,11,0.08) 0%, transparent 40%);
    }

    .card-detail {
        font-size: 0.85rem;
        color: var(--text-muted);
        margin-top: 0.35rem;
        display: block;
        line-height: 1.55;
    }

    /* ═══════════════════════════════════════════════
       Metric Cards
       ═══════════════════════════════════════════════ */
    .metric-row {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        flex: 1;
        background: var(--bg-card);
        backdrop-filter: blur(12px);
        border: 1px solid var(--border-subtle);
        border-radius: 14px;
        padding: 1.25rem 1.5rem;
        text-align: center;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(99,102,241,0.3);
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 800;
        line-height: 1.1;
        margin-bottom: 0.25rem;
    }
    .metric-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-muted);
        font-weight: 500;
    }
    .metric-pass .metric-value { color: var(--accent-emerald); }
    .metric-fail .metric-value { color: var(--accent-rose); }
    .metric-warn .metric-value { color: var(--accent-amber); }
    .metric-iter .metric-value {
        background: var(--gradient-main);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .metric-time .metric-value { color: var(--accent-sky); }

    /* ═══════════════════════════════════════════════
       Pipeline Progress Steps
       ═══════════════════════════════════════════════ */
    .pipeline-step {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.65rem 1rem;
        border-radius: 10px;
        margin-bottom: 0.4rem;
        font-size: 0.88rem;
        color: var(--text-primary);
        background: rgba(255,255,255,0.02);
        border: 1px solid transparent;
        transition: all 0.25s ease;
    }
    .pipeline-step:last-child {
        border-color: rgba(99,102,241,0.25);
        background: rgba(99,102,241,0.06);
    }
    .step-icon {
        width: 28px;
        height: 28px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.85rem;
        flex-shrink: 0;
    }
    .step-resolve .step-icon { background: rgba(56,189,248,0.15); }
    .step-generate .step-icon { background: rgba(168,85,247,0.15); }
    .step-grade .step-icon { background: rgba(16,185,129,0.15); }
    .step-soft_review .step-icon { background: rgba(245,158,11,0.15); }

    /* ═══════════════════════════════════════════════
       Sidebar Styling
       ═══════════════════════════════════════════════ */
    section[data-testid="stSidebar"] > div {
        padding-top: 1.5rem;
    }
    section[data-testid="stSidebar"] .stMarkdown h2 {
        font-size: 1.1rem;
        font-weight: 700;
        letter-spacing: -0.01em;
    }

    /* Primary Submit Button */
    [data-testid="stFormSubmitButton"] > button {
        background: var(--gradient-main) !important;
        color: white !important;
        border: none !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        border-radius: 10px !important;
        padding: 0.7rem 1.5rem !important;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
        box-shadow: 0 4px 15px rgba(99,102,241,0.3) !important;
        letter-spacing: 0.01em !important;
    }
    [data-testid="stFormSubmitButton"] > button:hover {
        transform: translateY(-2px) scale(1.01) !important;
        box-shadow: 0 8px 25px rgba(99,102,241,0.4) !important;
        filter: brightness(1.08) !important;
    }
    [data-testid="stFormSubmitButton"] > button:active {
        transform: translateY(0) scale(0.99) !important;
    }

    /* ═══════════════════════════════════════════════
       Tab Styling
       ═══════════════════════════════════════════════ */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.5rem;
        border-bottom: 1px solid var(--border-subtle);
        padding-bottom: 0;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        border-radius: 10px 10px 0 0;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        font-size: 0.88rem;
        transition: all 0.2s ease;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: rgba(99,102,241,0.1);
        border-bottom: 2px solid var(--accent-indigo);
    }

    /* ═══════════════════════════════════════════════
       Soft-review advisory note
       ═══════════════════════════════════════════════ */
    .advisory-note {
        padding: 1rem 1.25rem;
        border-radius: 12px;
        margin-bottom: 0.75rem;
        background: linear-gradient(90deg, rgba(56,189,248,0.06) 0%, transparent 50%);
        border: 1px solid rgba(56,189,248,0.15);
        border-left: 4px solid var(--accent-sky);
        color: var(--text-primary);
    }
    .advisory-note strong {
        color: var(--accent-sky);
        font-weight: 600;
    }
    .advisory-note .advisory-detail {
        font-size: 0.88rem;
        color: var(--text-muted);
        margin-top: 0.25rem;
        line-height: 1.55;
    }

    /* Main header margin tweak */
    .st-emotion-cache-1v0mbdj { margin-top: -3rem; }

    /* Progress bar coloring */
    .stProgress > div > div > div > div {
        background: var(--gradient-main);
    }
    </style>
""", unsafe_allow_html=True)


# --- Hero Header ---
st.markdown("""
<div class="hero-header">
    <h1>🧬 Pharma MLR Draft Pipeline</h1>
    <p>
        Generates a draft email/web mockup and runs it through a deterministic
        compliance-structure grader. Every output is a <strong>DRAFT</strong> for human MLR review —
        never an approved communication.
    </p>
</div>
""", unsafe_allow_html=True)


# --- Sidebar Configuration ---
with st.sidebar:
    st.markdown("## ⚙️ Campaign Configuration")

    with st.form("brief_form"):
        channel = st.selectbox("📡 Channel", [c.value for c in Channel], help="Structural switch — changes layout target.")
        email_type = st.selectbox("✉️ Email type", [e.value for e in EmailType]) if channel == "email" else None

        st.divider()
        market = st.text_input("🌍 Market", "UK", help="E.g., UK, US, EU. Unknowns fall back to AI classification.")
        audience = st.text_input("👥 Audience", "HCP", help="E.g., HCP, Patient.")
        brand = st.text_input("💊 Brand", "Dovato", help="Known: Dovato, Nucala, Trelegy, Shingrix.")
        classification = st.selectbox("🏷️ Classification", [c.value for c in ContentClassification])

        st.divider()
        objective = st.text_area("🎯 Objective", "Pre-launch HIV treatment awareness", height=80)
        uploaded_files = st.file_uploader("📎 Upload images (optional)", accept_multiple_files=True, type=["png", "jpg", "jpeg", "gif"])
        run_soft = st.checkbox("🔍 Run soft review (AI)", value=True, help="Runs 1 extra subjective AI call if structural checks pass.")

        submitted = st.form_submit_button("Generate Draft 🚀", use_container_width=True)


# --- Pipeline Execution ---
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
    pipeline_steps = []

    def ui_log(msg: str, node: str = ""):
        """Log a pipeline step with styled output."""
        node_icons = {"resolve": "🔍", "generate": "✨", "grade": "🛡️", "soft_review": "💬"}
        icon = node_icons.get(node, "→")
        pipeline_steps.append((node, msg))
        status_box.markdown(f"""
        <div class="pipeline-step step-{node}">
            <div class="step-icon">{icon}</div>
            <span>{msg}</span>
        </div>
        """, unsafe_allow_html=True)

    try:
        client = LLMClient()
    except RuntimeError as e:
        status_box.update(label="❌ Configuration Error", state="error")
        st.error(str(e))
        st.stop()

    t0 = time.time()
    graph = build_graph()
    final_state = {}

    ui_log(f"Soft review: {'**ON**' if run_soft else '**OFF**'}", "resolve")

    try:
        for step in graph.stream({
            "brief": brief, "client": client, "run_soft_review": run_soft,
            "iteration": 0, "prev_failed_ids": None,
        }):
            node_name = list(step.keys())[0]
            update = step[node_name]
            final_state.update(update)

            if node_name == "resolve":
                mi, ai = update["market_info"], update["audience_info"]
                ui_log(f"Market → **{mi.body_name}** (source: {mi.source})", "resolve")
                ui_log(f"Audience → **{'HCP' if ai.is_hcp else 'not HCP'}** (source: {ai.source})", "resolve")
            elif node_name == "generate":
                usage = client.last_usage or {}
                kind = "generated" if update["iteration"] == 1 else "revised"
                ui_log(f"Draft **{kind}** (attempt {update['iteration']}) — {usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens", "generate")
            elif node_name == "grade":
                report = update["grade_report"]
                ui_log(f"**{len(report.items)}** rules checked deterministically", "grade")
                if update.get("stuck"):
                    ui_log("⚠️ Repeated failure detected — stopping iteration early.", "grade")
            elif node_name == "soft_review":
                notes = update.get("soft_review_notes", [])
                ui_log(f"**{len(notes)}** advisory note(s)" if notes else "No concerns flagged ✓", "soft_review")

    except Exception as e:
        status_box.update(label="❌ Pipeline Error", state="error")
        st.error(f"Pipeline failed with an error:\n\n```\n{type(e).__name__}: {e}\n```\n\nCheck your Azure credentials, network connection, and API quota.")
        st.stop()

    elapsed = time.time() - t0
    report = final_state["grade_report"]
    status_box.update(
        label=f"{'✅' if report.all_passed else '⚠️'} Done — {final_state['iteration']} iteration(s), {elapsed:.1f}s",
        state="complete" if report.all_passed else "error",
    )

    # --- Metrics Summary ---
    passed_count = sum(1 for i in report.items if i.passed)
    failed_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.BLOCKING)
    warn_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.WARNING)
    total = len(report.items) if report.items else 1  # guard against division by zero

    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-card metric-pass">
            <div class="metric-value">{passed_count}</div>
            <div class="metric-label">Passed</div>
        </div>
        <div class="metric-card metric-fail">
            <div class="metric-value">{failed_count}</div>
            <div class="metric-label">Failed</div>
        </div>
        <div class="metric-card metric-warn">
            <div class="metric-value">{warn_count}</div>
            <div class="metric-label">Warnings</div>
        </div>
        <div class="metric-card metric-iter">
            <div class="metric-value">{final_state['iteration']}</div>
            <div class="metric-label">Iterations</div>
        </div>
        <div class="metric-card metric-time">
            <div class="metric-value">{elapsed:.1f}s</div>
            <div class="metric-label">Total Time</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Display Results in Tabs ---
    tab_preview, tab_audit, tab_code = st.tabs(["👁️ Live Preview", "🛡️ Audit & Grades", "💻 Raw Source"])

    html_raw = final_state["html"]
    html_preview = html_raw
    for fname, data_uri in brief.uploaded_images.items():
        html_preview = html_preview.replace(f"uploaded:{fname}", data_uri)

    with tab_preview:
        st.subheader("Rendered HTML Draft")
        if not report.all_passed:
            st.error("⚠️ This draft failed blocking compliance checks. It is **NOT** ready for distribution.")
        components.html(html_preview, height=800, scrolling=True)

        # Auto-save to outputs directory
        from pathlib import Path
        output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
        output_path = Path("outputs") / output_filename
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(html_raw, encoding="utf-8")
        st.success(f"💾 Saved to `{output_path}`")

        st.download_button("📥 Download HTML", data=html_preview, file_name=output_filename, mime="text/html")

    with tab_audit:
        st.subheader(f"Compliance Audit Report — Attempt {final_state['iteration']}")

        progress_val = passed_count / total
        st.progress(progress_val, text=f"{passed_count} / {total} Checks Passed")

        for item in report.items:
            if item.passed:
                status_class = "status-pass"
                icon = "✅"
            elif item.severity == Severity.WARNING:
                status_class = "status-warn"
                icon = "⚠️"
            else:
                status_class = "status-fail"
                icon = "❌"

            st.markdown(f"""
            <div class="status-card {status_class}">
                <strong>{icon} {item.label}</strong>
                <span class="card-detail">{item.detail}</span>
            </div>
            """, unsafe_allow_html=True)

        notes = final_state.get("soft_review_notes", [])
        if notes:
            st.markdown("---")
            st.subheader("💬 Soft Review Advisory (AI)")
            st.caption("These are a second AI's opinion — advisory only, never verified findings.")
            for n in notes:
                st.markdown(f"""
                <div class="advisory-note">
                    <strong>{n.concern}</strong>
                    <div class="advisory-detail">{n.detail}</div>
                </div>
                """, unsafe_allow_html=True)

    with tab_code:
        st.subheader("Raw Generated Code")
        st.code(html_raw, language="html")
