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
from growth_engine.feedback_triage import build_trial_patch_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local client trial patch plan from feedback and issue queues.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write patch plan outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_trial_patch_plan(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "feedback_triage_report": "analytics/feedback_triage_report.json",
        "client_patch_plan": "analytics/client_patch_plan.json",
        "client_response_notes": "analytics/client_response_notes.json",
        "trial_fix_backlog": "analytics/trial_fix_backlog.json",
        "trial_risk_summary": "analytics/trial_risk_summary.json",
        "trial_patch_plan_md": "out/client_delivery/TRIAL_PATCH_PLAN.md",
        "client_response_notes_md": "out/client_delivery/CLIENT_RESPONSE_NOTES.md",
        "trial_risk_summary_md": "out/client_delivery/TRIAL_RISK_SUMMARY.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
