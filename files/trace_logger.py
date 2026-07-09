"""
Trace logger — Loop 4 (hill-climbing loop) in loop-engineering terms.

Every pipeline run appends one JSON line per iteration to traces.jsonl:
which rules failed, on which brand/market, on which attempt number.
Run `python analyze_traces.py` after you've collected some runs to see
which rules the Generator struggles with most — that's your signal for
which part of prompts/generator_system.md to sharpen next, instead of
guessing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

TRACE_FILE = Path(__file__).parent / "traces.jsonl"


def log_iteration(brief, grade_report, iteration: int) -> None:
    record = {
        "ts": time.time(),
        "brand": brief.brand,
        "market": brief.market,
        "audience": brief.audience,
        "classification": brief.classification.value,
        "iteration": iteration,
        "all_passed": grade_report.all_passed,
        "failed_rules": [i.rule_id for i in grade_report.failed_items],
    }
    with TRACE_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")
