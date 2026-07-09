"""
Pipeline orchestrator — wires Loop 1 (generate) to Loop 2 (grade) with
a bounded revision loop, and logs every attempt for Loop 4 analysis.

IMPORTANT: `approved_for_production` on the result is hard-coded False.
Passing every automated check means the draft is structurally
complete, not that a qualified MLR reviewer has approved the clinical
claims, fair balance, and final copy. Don't let a UI or a future
version of this script quietly repurpose "all checks passed" as
"safe to send" — that decision has to stay with a human.
"""

from __future__ import annotations

from brand_config import get_brand_tokens
from generator import generate, revise
from grader import grade
from llm_client import LLMClient
from schema import CampaignBrief, PipelineResult
from trace_logger import log_iteration

MAX_ITERATIONS = 3


def run_pipeline(brief: CampaignBrief, client: LLMClient | None = None) -> PipelineResult:
    client = client or LLMClient()
    tokens = get_brand_tokens(brief.brand)

    html = generate(brief, client)
    report = grade(html, brief, tokens, iteration=1)
    log_iteration(brief, report, iteration=1)

    iteration = 1
    prev_failed_ids = None
    while not report.all_passed and iteration < MAX_ITERATIONS:
        current_failed_ids = tuple(sorted(i.rule_id for i in report.failed_items))
        if iteration > 1 and current_failed_ids == prev_failed_ids:
            # Same checks failed twice in a row. Stop instead of burning a 3rd identical call.
            break
        prev_failed_ids = current_failed_ids
        
        iteration += 1
        html = revise(brief, html, report, client)
        report = grade(html, brief, tokens, iteration=iteration)
        log_iteration(brief, report, iteration=iteration)

    return PipelineResult(
        brief=brief,
        final_html=html,
        grade_report=report,
        iterations_used=iteration,
        approved_for_production=False,  # always — see module docstring
    )


if __name__ == "__main__":
    # Quick manual smoke test — mirrors your sample input.
    client = LLMClient()
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="UK",
        audience="HCP",
        brand="Dovato",
        objective="Pre-launch HIV treatment awareness",
        classification="unbranded",
    )
    result = run_pipeline(brief, client=client)
    print(f"Iterations used: {result.iterations_used}")
    for item in result.grade_report.items:
        status = "PASSED" if item.passed else ("WARN" if item.severity == "warning" else "FAILED")
        print(f"  [{status}] {item.label} — {item.detail}")
    if client.last_usage:
        u = client.last_usage
        print(f"\nFinal call usage: {u.get('input_tokens')} in / {u.get('output_tokens')} out tokens")
        if u.get("cache_read_input_tokens"):
            print(f"  cache read: {u['cache_read_input_tokens']} tokens (~90% cheaper than fresh input)")
        if u.get("cache_creation_input_tokens"):
            print(f"  cache write: {u['cache_creation_input_tokens']} tokens (one-time 1.25x cost)")
    with open("last_run.html", "w") as f:
        f.write(result.final_html)
    print("\nWrote last_run.html")
