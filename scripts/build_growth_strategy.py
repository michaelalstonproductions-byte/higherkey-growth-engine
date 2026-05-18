#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.growth_strategy import build_growth_strategy


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local Growth Strategy Dashboard outputs. No cloud or social APIs.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Build the plan in memory without writing outputs.")
    parser.add_argument("--days", type=int, choices=(7, 30), default=30, help="Planning horizon.")
    args = parser.parse_args()
    summary = build_growth_strategy(Path(args.root), days=args.days, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
