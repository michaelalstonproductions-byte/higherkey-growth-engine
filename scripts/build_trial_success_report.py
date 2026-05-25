#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.trial_analytics import build_trial_success_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local client trial analytics and success reports.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write trial success outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_trial_success_report(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "trial_success_report": "analytics/trial_success_report.json",
        "client_trial_success_report": "analytics/client_trial_success_report.json",
        "internal_trial_analysis": "analytics/internal_trial_analysis.json",
        "next_trial_plan": "analytics/next_trial_plan.json",
        "client_trial_scorecard": "analytics/client_trial_scorecard.json",
        "trial_success_report_md": "out/client_delivery/TRIAL_SUCCESS_REPORT.md",
        "client_trial_summary_md": "out/client_delivery/CLIENT_TRIAL_SUMMARY.md",
        "next_trial_plan_md": "out/client_delivery/NEXT_TRIAL_PLAN.md",
        "internal_trial_analysis_md": "out/client_delivery/INTERNAL_TRIAL_ANALYSIS.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
