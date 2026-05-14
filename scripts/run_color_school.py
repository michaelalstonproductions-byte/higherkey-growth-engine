#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.color_school import analyze_color_school
from growth_engine.config import load_config
from growth_engine.events import append_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local read-only Color School analysis.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to the current directory.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum clips to analyze.")
    parser.add_argument("--quick", action="store_true", help="Analyze only a small bounded sample for QA.")
    args = parser.parse_args()
    limit = 3 if args.quick and args.limit is None else args.limit
    root = Path(args.root)
    report = analyze_color_school(root, limit=limit)
    append_event(load_config(root), "color_school.completed", severity=report.get("status", "info"), source="run_color_school", summary=report.get("summary", {}))
    print(json.dumps({
        "status": report.get("status"),
        "summary": report.get("summary"),
        "report_path": report.get("report_path"),
        "repair_plan_path": report.get("repair_plan_path"),
        "quick": bool(args.quick),
        "limit": limit,
        "read_only": True,
        "local_only": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
