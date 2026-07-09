"""
Run this after you've accumulated some traces.jsonl history to see
which rules the Generator trips on most, broken down by brand/market.
That's your prioritized list for sharpening generator_system.md —
data-driven prompt iteration instead of vibes.

Usage: python analyze_traces.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

TRACE_FILE = Path(__file__).parent / "traces.jsonl"


def main():
    if not TRACE_FILE.exists():
        print("No traces.jsonl yet — run pipeline.py a few times first.")
        return

    records = [json.loads(line) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    first_attempts = [r for r in records if r["iteration"] == 1]

    rule_fail_counts = Counter()
    for r in first_attempts:
        rule_fail_counts.update(r["failed_rules"])

    print(f"Total runs: {len(first_attempts)}")
    print(f"First-attempt pass rate: {sum(r['all_passed'] for r in first_attempts) / max(len(first_attempts),1):.0%}\n")

    print("Rules that fail most often on the FIRST attempt (fix these in the prompt first):")
    for rule, count in rule_fail_counts.most_common():
        pct = count / max(len(first_attempts), 1)
        print(f"  {rule:20s} failed {count:3d}x  ({pct:.0%} of runs)")

    avg_iters = sum(r["iteration"] for r in records if r["all_passed"]) / max(
        sum(1 for r in records if r["all_passed"]), 1
    )
    print(f"\nAvg iterations to pass (when it passes): {avg_iters:.1f}")


if __name__ == "__main__":
    main()
