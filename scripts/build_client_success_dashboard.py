#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.client_success import build_client_success_dashboard
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local client success dashboard and trial closeout reports.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write client success outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_client_success_dashboard(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "client_success_dashboard": "analytics/client_success_dashboard.json",
        "client_trial_closeout_report": "analytics/client_trial_closeout_report.json",
        "operator_closeout_checklist": "analytics/operator_closeout_checklist.json",
        "next_engagement_recommendation": "analytics/next_engagement_recommendation.json",
        "client_success_summary": "analytics/client_success_summary.json",
        "client_success_dashboard_md": "out/client_delivery/CLIENT_SUCCESS_DASHBOARD.md",
        "trial_closeout_report_md": "out/client_delivery/TRIAL_CLOSEOUT_REPORT.md",
        "operator_closeout_checklist_md": "out/client_delivery/OPERATOR_CLOSEOUT_CHECKLIST.md",
        "next_engagement_recommendation_md": "out/client_delivery/NEXT_ENGAGEMENT_RECOMMENDATION.md",
        "client_success_summary_md": "out/client_delivery/CLIENT_SUCCESS_SUMMARY.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
