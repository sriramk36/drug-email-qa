"""
Streamlit UI — runs on pipeline_langgraph.py's graph, not the plain
pipeline.py loop. Uses graph.stream() to get a live update after every
node (resolve / generate / grade / soft_review) with zero manual
ui_log() plumbing inside the loop logic itself — that per-step
visibility is what LangGraph gives you for free versus the plain
version, and this file is where that actually gets used, not just
demonstrated in a CLI print statement.

--- Changes in this revision ---
1. Draft preview now inline-highlights any quoted phrase referenced by a
   failed/warned audit item, so reviewers see the offending copy in
   context instead of only in the side panel.
2. Audit results are grouped into Blocking Failures / Warnings / Passed
   expanders (with counts) instead of one flat list.
3. An "Iteration History" strip shows pass/fail/warn deltas across
   retries, so it's clear *why* the pipeline looped.
4. Every run now persists a small JSON sidecar next to its HTML output.
   A "Recent Drafts" section reads these back into a history table
   (ID, channel, market, audience, objective, compliance score, status,
   iterations, created at) that's visible even before you generate a
   new draft.

Run with: streamlit run app.py
"""

import time
import base64
import json
import re
import textwrap
from datetime import datetime
from pathlib import Path

import pandas as pd
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
    .status-info {
        border-left: 4px solid var(--accent-sky);
        background: linear-gradient(90deg, rgba(56,189,248,0.08) 0%, transparent 40%);
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
    .delta-grid {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.95rem;
    }
    .delta-grid th,
    .delta-grid td {
        padding: 0.85rem 1rem;
        border: 1px solid rgba(148,163,184,0.18);
    }
    .delta-grid th {
        background: rgba(99,102,241,0.08);
        color: var(--text-primary);
        text-align: left;
        width: 25%;
    }
    .delta-cell {
        color: var(--text-muted);
        line-height: 1.5;
    }
    .delta-pass { color: var(--accent-emerald); }
    .delta-warn { color: var(--accent-amber); }
    .delta-fail { color: var(--accent-rose); }
    .log-timestamp {
        color: #94a3b8;
        font-size: 0.75rem;
        margin-left: 0.7rem;
    }
    .step-content {
        display: flex;
        justify-content: space-between;
        width: 100%;
        gap: 1rem;
        align-items: center;
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
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
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

    /* ═══════════════════════════════════════════════
       Recent Drafts history table
       ═══════════════════════════════════════════════ */
    .history-heading {
        font-weight: 700;
        font-size: 1.05rem;
        margin: 1.5rem 0 0.5rem 0;
        color: var(--text-primary);
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


# --- Helper functions (history + inline highlighting) ---

def highlight_flagged_claims(html: str, report) -> str:
    """Wrap any quoted phrase referenced in a failed/warned audit item's
    detail text in a <mark> tag, so the offending copy is visible directly
    inside the draft preview instead of only in the side audit panel.

    components.html() renders in its own sandboxed iframe, so the styling
    for the <mark> tags has to be injected into this HTML string itself —
    the app's main <style> block above won't reach inside that iframe.
    """
    highlighted = html
    for item in report.items:
        if item.passed:
            continue
        css_class = "mlr-flag-fail" if item.severity == Severity.BLOCKING else "mlr-flag-warn"
        quotes = re.findall(r'"([^"\n]{3,80})"', item.detail or "")
        for q in quotes:
            if q and q in highlighted:
                highlighted = highlighted.replace(
                    q, f'<mark class="{css_class}" title="{item.label}">{q}</mark>', 1
                )
    style_snippet = """
    <style>
    mark.mlr-flag-fail{background:rgba(244,63,94,0.25);color:#f43f5e;padding:0 2px;border-radius:3px;border-bottom:2px solid #f43f5e;}
    mark.mlr-flag-warn{background:rgba(245,158,11,0.25);color:#f59e0b;padding:0 2px;border-radius:3px;border-bottom:2px solid #f59e0b;}
    </style>
    """
    return style_snippet + highlighted


def save_draft_metadata(brief, report, iteration, elapsed, output_filename, passed, failed, warned, total):
    """Persist a small JSON sidecar next to each generated draft so the
    'Recent Drafts' section below can list history across sessions,
    instead of only showing the single most recent run."""
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    existing = list(out_dir.glob("*.json"))
    draft_id = f"#{1200 + len(existing) + 1}"
    meta = {
        "id": draft_id,
        "channel": brief.channel,
        "type": brief.email_type or "-",
        "market": brief.market,
        "audience": brief.audience,
        "brand": brief.brand,
        "objective": brief.objective,
        "classification": brief.classification,
        "status": "Draft" if report.all_passed else "Blocked",
        "compliance": f"{passed}/{total}",
        "iterations": iteration,
        "time_taken": f"{elapsed:.1f}s",
        "created_at": datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "html_file": output_filename,
    }
    meta_path = out_dir / f"{Path(output_filename).stem}.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_draft_history():
    out_dir = Path("outputs")
    if not out_dir.exists():
        return []
    records = []
    for jf in sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            records.append(json.loads(jf.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def render_verification_diff(snapshot: dict[str, list[str]]) -> None:
    if not snapshot:
        return
    rows = []
    if snapshot.get("rectified_rules"):
        rows.append(("Rectified", snapshot["rectified_rules"], "delta-pass"))
    if snapshot.get("still_failing"):
        rows.append(("Still failing", snapshot["still_failing"], "delta-warn"))
    if snapshot.get("new_failures"):
        rows.append(("New failures", snapshot["new_failures"], "delta-fail"))
    if not rows:
        st.markdown("*No rule changes detected in this iteration.*")
        return
    table_rows = "".join(
        f"<tr><th>{label}</th><td class='delta-cell {cls}'>{', '.join(values)}</td></tr>"
        for label, values, cls in rows
    )
    st.markdown(f"""
    <table class="delta-grid">
        {table_rows}
    </table>
    """, unsafe_allow_html=True)


def render_recent_drafts():
    st.markdown('<div class="history-heading">📋 Recent Drafts</div>', unsafe_allow_html=True)
    records = load_draft_history()
    if not records:
        st.caption("No drafts generated yet — your history will appear here after your first run.")
        return
    df = pd.DataFrame(records)
    df = df.rename(columns={
        "id": "ID", "channel": "Channel", "type": "Type", "market": "Market",
        "audience": "Audience", "objective": "Objective", "compliance": "Compliance",
        "status": "Status", "iterations": "Iterations", "created_at": "Created At",
    })
    display_cols = ["ID", "Channel", "Type", "Market", "Audience", "Objective",
                     "Compliance", "Status", "Iterations", "Created At"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols].head(10), use_container_width=True, hide_index=True)


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

    status_card = st.empty()
    pipeline_log = st.empty()
    node_icons = {"resolve": "🔍", "generate": "✨", "grade": "🛡️", "soft_review": "💬"}

    def render_status_card(title: str, status: str = "running", detail: str = "Live verification loop updates appear below as each stage completes."):
        if status == "running":
            type_class = "status-info"
        elif status == "success":
            type_class = "status-pass"
        elif status == "warn":
            type_class = "status-warn"
        elif status == "error":
            type_class = "status-fail"
        else:
            type_class = "status-pass"
        status_card.markdown(f"""
        <div class="status-card {type_class}" style="padding:1rem; margin-bottom:1rem;">
            <strong>{title}</strong>
            <div style="color:#8b949e; margin-top:0.35rem;">{detail}</div>
        </div>
        """, unsafe_allow_html=True)
    render_status_card("🧠 Running LangGraph pipeline...", "running")
    pipeline_steps = []
    iteration_history = []  # tracks pass/fail/warn counts across retries
    prev_failed_items = []
    current_iteration = 0

    def render_pipeline_log() -> None:
        rendered = [
            "<div style='margin-bottom:0.75rem; font-weight:700; color:#e6edf3;'>🔁 Verification Loop</div>"
        ]
        for node, msg, timestamp in pipeline_steps:
            icon = node_icons.get(node, "→")
            time_label = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
            rendered.append(textwrap.dedent(f"""<div class="pipeline-step step-{node}">
                <div class="step-icon">{icon}</div>
                <div class="step-content">
                    <span>{msg}</span>
                    <span class="log-timestamp">{time_label}</span>
                </div>
            </div>""").strip())
        pipeline_log.markdown("".join(rendered), unsafe_allow_html=True)

    def ui_log(msg: str, node: str = ""):
        """Log a pipeline step with styled output."""
        pipeline_steps.append((node, msg, time.time()))
        render_pipeline_log()

    try:
        client = LLMClient()
    except RuntimeError as e:
        render_status_card("❌ Configuration Error", "error", "Missing Azure OpenAI credentials or incorrect configuration.")
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
                render_status_card("🧠 Resolution complete", "running", f"Resolved market and audience for the first draft.")
            elif node_name == "generate":
                current_iteration = update.get("iteration", final_state.get("iteration", 0) + 1)
                usage = client.last_usage or {}
                kind = "generated" if current_iteration == 1 else "revised"
                if current_iteration == 1:
                    render_status_card(f"✨ Generation {current_iteration} complete", "running", "Now verifying the first draft against compliance rules.")
                    ui_log(f"First draft generated (attempt {current_iteration}) — {usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens", "generate")
                else:
                    failed_ids = [item.rule_id for item in prev_failed_items]
                    render_status_card(f"✨ Revision {current_iteration} complete", "running", f"Draft revised to address {len(failed_ids)} previously failed rule(s). Verifying again.")
                    ui_log(f"Revised draft generated (attempt {current_iteration}) — fixing {', '.join(failed_ids)}", "generate")
            elif node_name == "grade":
                report = update["grade_report"]
                current_iteration = final_state.get("iteration", 0)
                failed_items = [i for i in report.failed_items if i.severity == Severity.BLOCKING]
                warn_items = [i for i in report.items if not i.passed and i.severity == Severity.WARNING]
                failed_rules = [i.rule_id for i in failed_items]
                warn_rules = [i.rule_id for i in warn_items]
                snap_passed = sum(1 for i in report.items if i.passed)
                snap_failed = len(failed_rules)
                snap_warned = len(warn_rules)
                prior_failed_ids = [item.rule_id for item in prev_failed_items]
                rectified_rules = [rule for rule in prior_failed_ids if rule not in failed_rules]
                still_failing = [rule for rule in failed_rules if rule in prior_failed_ids]
                new_failures = [rule for rule in failed_rules if rule not in prior_failed_ids]
                iteration_history.append({
                    "attempt": current_iteration,
                    "passed": snap_passed, "failed": snap_failed, "warned": snap_warned,
                    "failed_rules": failed_rules,
                    "new_failures": new_failures,
                    "still_failing": still_failing,
                    "rectified_rules": rectified_rules,
                    "concepts": [
                        {"rule_id": it.rule_id, "passed": it.passed, "label": it.label, "detail": it.detail}
                        for it in report.items
                    ],
                })
                prev_failed_items = failed_items
                if report.all_passed:
                    render_status_card(f"✅ Generation {current_iteration} passed", "success", "All deterministic blocking checks passed. Soft review will run if enabled.")
                    ui_log(f"Generation {current_iteration} passed all blocking checks.", "grade")
                else:
                    render_status_card(f"❌ Generation {current_iteration} failed", "error", f"Failed rules: {', '.join(failed_rules)}")
                    ui_log(f"Generation {current_iteration} failed {snap_failed} blocking rule(s) and {snap_warned} warning(s).", "grade")
                    if rectified_rules or still_failing or new_failures:
                        sections = []
                        if rectified_rules:
                            sections.append(f"<div><strong>Rectified from prior attempt:</strong> {', '.join(rectified_rules)}</div>")
                        if still_failing:
                            sections.append(f"<div><strong>Still failing:</strong> {', '.join(still_failing)}</div>")
                        if new_failures:
                            sections.append(f"<div><strong>New failures this iteration:</strong> {', '.join(new_failures)}</div>")
                        pipeline_log.markdown(textwrap.dedent(f"""<div style='padding:0.65rem 1rem; border-radius:10px; background:#0f172a; margin:0.5rem 0;'>
                            {''.join(sections)}
                        </div>""").strip(), unsafe_allow_html=True)
                    if failed_items:
                        detail_rows = "".join(
                            f"<div style='margin-top:0.35rem;'><strong>{item.rule_id}</strong>: {item.detail}</div>"
                            for item in failed_items
                        )
                        pipeline_log.markdown(textwrap.dedent(f"""<div style='padding:0.65rem 1rem; border-radius:10px; background:#13161c; margin:0.5rem 0;'>
                            <strong>Iteration {current_iteration} failures:</strong>
                            {detail_rows}
                        </div>""").strip(), unsafe_allow_html=True)
                if update.get("stuck"):
                    ui_log("⚠️ Repeated failure detected — stopping iteration early.", "grade")
            elif node_name == "soft_review":
                notes = update.get("soft_review_notes", [])
                ui_log(f"**{len(notes)}** advisory note(s)" if notes else "No concerns flagged ✓", "soft_review")
                render_status_card("💬 Soft review complete", "running", f"Soft review produced {len(notes)} advisory note(s).")

    except Exception as e:
        render_status_card("❌ Pipeline Error", "error", "Pipeline failed with an error. See the message below.")
        st.error(f"Pipeline failed with an error:\n\n```\n{type(e).__name__}: {e}\n```\n\nCheck your Azure credentials, network connection, and API quota.")
        st.stop()

    elapsed = time.time() - t0
    report = final_state["grade_report"]
    summary_title = f"{'✅' if report.all_passed else '⚠️'} Done — {final_state['iteration']} iteration(s), {elapsed:.1f}s"
    summary_detail = "This draft passed all blocking checks." if report.all_passed else "This draft has blocking/warning issues and is not ready for distribution."
    render_status_card(summary_title, "success" if report.all_passed else "error", summary_detail)

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

        # Fix: flag failing/warned claims directly inside the preview,
        # not just in the side audit panel.
        preview_with_flags = highlight_flagged_claims(html_preview, report)
        components.html(preview_with_flags, height=800, scrolling=True)

        # Auto-save to outputs directory
        output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
        output_path = Path("outputs") / output_filename
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(html_raw, encoding="utf-8")

        # Fix: persist a metadata sidecar so this run shows up in
        # "Recent Drafts" below, across sessions.
        meta = save_draft_metadata(
            brief, report, final_state["iteration"], elapsed, output_filename,
            passed_count, failed_count, warn_count, total,
        )
        st.success(f"💾 Saved to `{output_path}` (ID {meta['id']})")

        st.download_button("📥 Download HTML", data=html_preview, file_name=output_filename, mime="text/html")

    with tab_audit:
        st.subheader(f"Compliance Audit Report — Attempt {final_state['iteration']}")

        # Fix: show why the pipeline looped, iteration by iteration.
        if len(iteration_history) > 1:
            st.markdown("##### 🔁 Iteration History")
            cols = st.columns(len(iteration_history))
            for idx, snap in enumerate(iteration_history):
                with cols[idx]:
                    st.metric(f"Attempt {snap['attempt']}", f"{snap['passed']} ✓ {snap['failed']} ✗ {snap['warned']} ⚠")
            st.caption("Each attempt regenerates the draft and re-runs the deterministic grader until it passes or the retry limit is hit.")

            # Show per-attempt detailed checklist of concepts
            for snap in iteration_history:
                with st.expander(f"Attempt {snap['attempt']} — {snap['passed']} ✓ {snap['failed']} ✗ {snap['warned']} ⚠", expanded=False):
                    # Summary deltas for this attempt
                    if snap["rectified_rules"] or snap["still_failing"] or snap["new_failures"]:
                        render_verification_diff(snap)

                    # Checklist: show each rule's status and short detail
                    checklist_html = []
                    for c in snap.get("concepts", []):
                        icon = "✅" if c["passed"] else "❌"
                        cls = "delta-pass" if c["passed"] else "delta-fail"
                        checklist_html.append(f"<div style='margin:0.25rem 0;'><strong>{icon} {c['rule_id']}</strong> — <span class='delta-cell {cls}'>{c['label']}</span><div style='color:#94a3b8;margin-left:1rem;font-size:0.9rem'>{c['detail']}</div></div>")
                    st.markdown("".join(checklist_html), unsafe_allow_html=True)

        progress_val = passed_count / total
        st.progress(progress_val, text=f"{passed_count} / {total} Checks Passed")

        def render_item(item):
            icon = "✅" if item.passed else ("⚠️" if item.severity == Severity.WARNING else "❌")
            status_class = "status-pass" if item.passed else ("status-warn" if item.severity == Severity.WARNING else "status-fail")
            st.markdown(f"""
            <div class="status-card {status_class}">
                <strong>{icon} {item.label}</strong>
                <span class="card-detail">{item.detail}</span>
            </div>
            """, unsafe_allow_html=True)

        # Fix: group by severity instead of one flat list, so blocking
        # issues can't get lost among dozens of passed checks.
        blocking_items = [i for i in report.items if not i.passed and i.severity == Severity.BLOCKING]
        warning_items = [i for i in report.items if not i.passed and i.severity == Severity.WARNING]
        passed_items = [i for i in report.items if i.passed]

        if blocking_items:
            with st.expander(f"❌ Blocking Failures ({len(blocking_items)})", expanded=True):
                for item in blocking_items:
                    render_item(item)

        if warning_items:
            with st.expander(f"⚠️ Warnings ({len(warning_items)})", expanded=True):
                for item in warning_items:
                    render_item(item)

        with st.expander(f"✅ Passed Checks ({len(passed_items)})", expanded=False):
            for item in passed_items:
                render_item(item)

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

# --- Recent Drafts (always visible, persists across sessions/reruns) ---
st.markdown("---")
render_recent_drafts()