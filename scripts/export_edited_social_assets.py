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
from growth_engine.editing_manifest import export_edited_social_assets


def main() -> int:
    parser = argparse.ArgumentParser(description="Export approved edited assets into local social pack folders.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--platform")
    parser.add_argument("--clip-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    dry_run = True if args.dry_run or not args.approve else False
    result = export_edited_social_assets(
        config,
        approve=args.approve,
        dry_run=dry_run,
        platform=args.platform,
        clip_id=args.clip_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "approval_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
