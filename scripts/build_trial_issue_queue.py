#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.client_feedback import build_issue_queue
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local client trial issue queue.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write issue queue outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_issue_queue(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "issue_count": result.get("issue_count"),
        "dry_run": result.get("dry_run"),
        "client_issue_queue": "analytics/client_issue_queue.json",
        "client_trial_status": "analytics/client_trial_status.json",
        "trial_issue_queue_md": "out/client_delivery/TRIAL_ISSUE_QUEUE.md",
        "trial_fix_plan_md": "out/client_delivery/TRIAL_FIX_PLAN.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
