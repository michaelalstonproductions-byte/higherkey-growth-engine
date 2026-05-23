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
from growth_engine.editing_delivery import package_edited_assets


def main() -> int:
    parser = argparse.ArgumentParser(description="Package approved edited assets for client delivery.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--include-previews", action="store_true")
    parser.add_argument("--include-final-renders", action="store_true")
    parser.add_argument("--include-edited-social-packs", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(Path.cwd())
    dry_run = True if args.dry_run or not args.approve else False
    result = package_edited_assets(
        config,
        approve=args.approve,
        dry_run=dry_run,
        include_previews=args.include_previews,
        include_final_renders=True,
        include_edited_social_packs=args.include_edited_social_packs,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
