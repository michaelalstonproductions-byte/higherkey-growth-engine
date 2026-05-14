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
from growth_engine.state_reconciler import reconcile_state


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile HigherKey runtime DB, JSON snapshots, and generated files.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", help="Report issues without applying safe metadata repairs. Default.")
    parser.add_argument("--apply", action="store_true", help="Apply safe non-destructive metadata repairs.")
    parser.add_argument("--json", action="store_true", help="Print the full reconciliation report JSON.")
    parser.add_argument("--limit", type=int, default=None, help="Limit reported issues.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = reconcile_state(config, apply=args.apply, limit=args.limit)
    summary = {
        "status": result["report"]["status"],
        "severity": result["report"]["severity"],
        "applied": result["report"]["applied"],
        "issue_count": result["report"]["issue_count"],
        "repairable_issue_count": result["report"]["repairable_issue_count"],
        "state_reconciliation_report": "analytics/state_reconciliation_report.json",
        "client_integrity": "analytics/client_integrity.json",
        "quarantine_report": "analytics/quarantine_report.json",
        "local_only": True,
    }
    print(json.dumps(result["report"] if args.json else summary, indent=2, sort_keys=True))
    return 0 if result["report"]["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
