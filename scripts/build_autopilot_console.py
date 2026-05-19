#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.autopilot_console import build_autopilot_console


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local Operator Autopilot run console.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing console outputs.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args()
    summary = build_autopilot_console(Path(args.root), dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
