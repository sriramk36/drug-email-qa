import sys
import uuid
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from agents.export_utils import build_html_export, build_text_export
from agents.image_analyzer import analyze_image
from graph import run_verification_loop

st.set_page_config(
    page_title="Drug Email QA",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetric"] {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 12px 16px;
    }
    .check-pass { border-left: 4px solid #22c55e; padding-left: 12px; margin-bottom: 8px; }
    .check-fail { border-left: 4px solid #ef4444; padding-left: 12px; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

st.title("Drug Email QA")
st.caption("Generate healthcare email drafts, review against compliance rules, and inspect the verification loop.")

with st.sidebar:
    st.header("Campaign Inputs")
    drug = st.text_input("Drug name", value="NovaMed")
    audience = st.text_input("Target audience", value="Adults 30-50")
    goal = st.text_input("Campaign goal", value="Drug awareness")
    message = st.text_area(
        "Key message",
        value="Educate about safe usage and encourage professional guidance",
        height=100,
    )
    image_file = st.file_uploader("Hero image (optional)", type=["png", "jpg", "jpeg", "webp"])
    run_button = st.button("Run verification loop", type="primary", use_container_width=True)

    if run_button:
        image_info = {"available": False}
        if image_file is not None:
            upload_path = ROOT / "uploads" / f"{uuid.uuid4().hex}_{image_file.name}"
            upload_path.parent.mkdir(parents=True, exist_ok=True)
            with upload_path.open("wb") as fh:
                fh.write(image_file.getbuffer())
            try:
                image_info = analyze_image(str(upload_path))
            finally:
                upload_path.unlink(missing_ok=True)

    campaign = {
        "drug": drug,
        "audience": audience,
        "goal": goal,
        "message": message,
    }

    with st.spinner("Running verification loop…"):
        result = run_verification_loop(campaign, image_info=image_info)

    passed = result["passed"]
    st.markdown(
        f"### {'✅ Passed all checks' if passed else '⚠️ Needs revision'}"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Attempts", result["attempts"])
    col2.metric("Overall score", result["review"]["overall_score"])
    checks = result["review"].get("checks", {})
    passed_count = sum(1 for c in checks.values() if c.get("passed"))
    col3.metric("Checks passed", f"{passed_count}/{len(checks)}")

    tab_email, tab_checks, tab_timeline, tab_logs = st.tabs(
        ["Email preview", "Review checks", "Attempt timeline", "Raw logs"]
    )

    with tab_email:
        st.text_area("Generated email", result["email"], height=280, label_visibility="collapsed")
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "Download HTML",
                build_html_export(result["email"], result),
                file_name="drug-email-export.html",
                mime="text/html",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "Download TXT",
                build_text_export(result["email"], result),
                file_name="drug-email-export.txt",
                mime="text/plain",
                use_container_width=True,
            )
        if image_info.get("available"):
            st.subheader("Image analysis")
            st.json(image_info)

    with tab_checks:
        for name, check in checks.items():
            label = name.replace("_", " ").title()
            css = "check-pass" if check["passed"] else "check-fail"
            status = "Passed" if check["passed"] else "Failed"
            st.markdown(
                f'<div class="{css}"><strong>{label}</strong> — {status} (score {check["score"]})</div>',
                unsafe_allow_html=True,
            )
            if check.get("issues"):
                for issue in check["issues"]:
                    st.caption(f"• {issue}")

    with tab_timeline:
        reviews = result.get("logs", {}).get("auditor", {}).get("reviews", [])
        if reviews:
            for i, review in enumerate(reviews, 1):
                icon = "✅" if review["passed"] else "❌"
                with st.expander(f"{icon} Attempt {i} — score {review['overall_score']}", expanded=i == len(reviews)):
                    if review.get("issues"):
                        for issue in review["issues"]:
                            st.write(f"- {issue}")
                    else:
                        st.write("All checks passed.")
        else:
            st.info("No attempt history available.")

    with tab_logs:
        st.json(result)
else:
    st.info("Configure campaign inputs in the sidebar and click **Run verification loop** to begin.")
