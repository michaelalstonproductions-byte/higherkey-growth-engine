#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.operator_autopilot import approve_action, build_operator_autopilot, run_safe_actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe local Operator Autopilot actions. Dry-run by default.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview actions without executing them.")
    parser.add_argument("--apply", action="store_true", help="Execute selected safe-auto actions. Requires --safe-auto.")
    parser.add_argument("--safe-auto", action="store_true", help="Allow execution of safe-auto allowlisted local actions.")
    parser.add_argument("--action-id", help="Limit to one action id.")
    parser.add_argument("--approve-action-id", help="Record local approval receipt for one action id.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args()
    root = Path(args.root)
    build_operator_autopilot(root, dry_run=False)
    if args.approve_action_id:
        summary = approve_action(root.resolve(), args.approve_action_id)
    else:
        summary = run_safe_actions(root, safe_auto=args.safe_auto, action_id=args.action_id, dry_run=not args.apply)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
