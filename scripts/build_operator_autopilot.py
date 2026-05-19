#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.operator_autopilot import build_operator_autopilot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local Operator Autopilot plan. No cloud or social posting APIs.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Build in memory without writing outputs.")
    parser.add_argument("--mode", choices=["plan", "safe-auto", "approvals"], default="plan", help="Planning view to summarize.")
    args = parser.parse_args()
    summary = build_operator_autopilot(Path(args.root), dry_run=args.dry_run)
    summary["mode"] = args.mode
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
