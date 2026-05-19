#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.creative_director import build_creative_direction


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local Creative Director Studio outputs. No cloud or social APIs.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Build in memory without writing outputs.")
    parser.add_argument("--clip-id", help="Limit creative direction to one clip.")
    parser.add_argument("--platform", help="Limit creative direction to one platform.")
    parser.add_argument("--count", type=int, default=20, help="Hook planning count. Defaults to 20.")
    args = parser.parse_args()
    summary = build_creative_direction(Path(args.root), clip_id=args.clip_id, platform=args.platform, count=args.count, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
