#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.marketing_intelligence import import_instagram_insights


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Instagram insights from a local JSON/CSV export. No live API calls.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--input", default=None, help="Path to local instagram_insights.json or .csv.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without importing records.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    input_path = Path(args.input).expanduser().resolve() if args.input else None
    summary = import_instagram_insights(root, input_path=input_path, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
