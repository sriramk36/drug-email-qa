"""Build downloadable HTML and plain-text exports for generated emails."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Tuple


def parse_email_sections(text: str) -> List[Tuple[str, str]]:
    if not text:
        return []
    sections: List[Tuple[str, str]] = []
    patterns = [
        ("Subject", r"(?:^|\n)\s*subject\s*:\s*(.+?)(?=\n\s*(?:body|message|cta|call to action)\s*:|$)"),
        ("Body", r"(?:^|\n)\s*(?:body|message)\s*:\s*(.+?)(?=\n\s*(?:cta|call to action)\s*:|$)"),
        ("Call to Action", r"(?:^|\n)\s*(?:cta|call to action)\s*:\s*(.+)"),
    ]
    for label, regex in patterns:
        match = re.search(regex, text, re.IGNORECASE | re.DOTALL)
        if match:
            sections.append((label, match.group(1).strip()))
    return sections


def build_text_export(email: str, result: Dict[str, Any] | None = None) -> str:
    lines = ["Drug Email QA — Generated Email", "=" * 40, "", email.strip(), ""]
    if result:
        lines.extend([
            "Verification Summary",
            "-" * 40,
            f"Passed: {result.get('passed')}",
            f"Attempts: {result.get('attempts')}",
            f"Score: {result.get('review', {}).get('overall_score')}",
        ])
        feedback = result.get("review", {}).get("feedback") or []
        if feedback:
            lines.append("")
            lines.append("Feedback:")
            lines.extend(f"  - {item}" for item in feedback)
    return "\n".join(lines)


def build_html_export(email: str, result: Dict[str, Any] | None = None) -> str:
    sections = parse_email_sections(email)
    if sections:
        body_html = "".join(
            f'<section class="block"><h2>{html.escape(label)}</h2>'
            f'<p>{html.escape(content).replace(chr(10), "<br>")}</p></section>'
            for label, content in sections
        )
    else:
        body_html = f'<pre class="raw">{html.escape(email)}</pre>'

    summary_html = ""
    if result:
        passed = result.get("passed")
        status = "Passed" if passed else "Needs revision"
        status_class = "pass" if passed else "fail"
        review = result.get("review", {})
        feedback_items = "".join(
            f"<li>{html.escape(str(item))}</li>" for item in (review.get("feedback") or [])
        )
        summary_html = f"""
        <section class="summary">
          <h2>Verification Summary</h2>
          <p class="status {status_class}">{html.escape(status)}</p>
          <ul class="meta">
            <li>Attempts: {html.escape(str(result.get('attempts', '—')))}</li>
            <li>Score: {html.escape(str(review.get('overall_score', '—')))}</li>
          </ul>
          {'<ul class="feedback">' + feedback_items + '</ul>' if feedback_items else ''}
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Drug Email QA Export</title>
  <style>
    body {{ font-family: Georgia, serif; max-width: 720px; margin: 40px auto; padding: 0 24px; color: #1f2937; }}
    h1 {{ font-size: 1.5rem; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }}
    h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; color: #2563eb; margin-bottom: 8px; }}
    .block {{ margin-bottom: 24px; }}
    .block p {{ line-height: 1.7; margin: 0; }}
    .summary {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin-bottom: 32px; }}
    .status {{ font-weight: 700; }}
    .status.pass {{ color: #15803d; }}
    .status.fail {{ color: #b91c1c; }}
    .meta, .feedback {{ margin: 8px 0 0; padding-left: 20px; }}
    .raw {{ white-space: pre-wrap; background: #f1f5f9; padding: 16px; border-radius: 8px; }}
    @media print {{ body {{ margin: 20px; }} }}
  </style>
</head>
<body>
  <h1>Drug Email QA Export</h1>
  {summary_html}
  {body_html}
</body>
</html>"""
