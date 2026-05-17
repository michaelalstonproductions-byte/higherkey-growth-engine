#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.campaign_planner import build_campaign_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local campaign board and posting plan outputs.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--days", type=int, default=30, choices=(7, 30), help="Schedule horizon to prioritize.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary. Default also prints JSON for automation.")
    parser.add_argument("--dry-run", action="store_true", help="Build the plan in memory without writing campaign outputs.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    summary = build_campaign_plan(root, days=args.days, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
