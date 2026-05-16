#!/usr/bin/env python3
"""Evaluate Data QA nightly report for SCHEMA_DRIFT_ALERT."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.data_agent.data_qa_drift import evaluate_schema_drift_alert  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON report with ci_passed, nightly_total and nightly_failed")
    parser.add_argument("--failure-threshold", type=float, default=0.3)
    parser.add_argument("--min-cases", type=int, default=5)
    args = parser.parse_args()

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    evaluation = evaluate_schema_drift_alert(
        ci_passed=bool(payload["ci_passed"]),
        nightly_total=int(payload["nightly_total"]),
        nightly_failed=int(payload["nightly_failed"]),
        failure_threshold=args.failure_threshold,
        min_cases=args.min_cases,
    )
    print(json.dumps(evaluation.to_dict(), ensure_ascii=False, sort_keys=True))
    return 2 if evaluation.alert else 0


if __name__ == "__main__":
    raise SystemExit(main())
