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
from growth_engine.feedback_triage import TRIAGE_STATUSES, update_trial_issue_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Update a local trial issue or triage item status.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--issue-id", default="", help="Issue ID to update.")
    parser.add_argument("--triage-id", default="", help="Triage ID to update.")
    parser.add_argument("--status", default="triaged", choices=sorted(TRIAGE_STATUSES), help="New local status.")
    parser.add_argument("--note", default="", help="Local operator note.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write status outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = update_trial_issue_status(
        config,
        issue_id=args.issue_id,
        triage_id=args.triage_id,
        status=args.status,
        note=args.note,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
