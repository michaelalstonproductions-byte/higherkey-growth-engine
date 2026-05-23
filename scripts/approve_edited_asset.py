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
from growth_engine.editing_approval import approve_edited_asset


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve a specific edited asset locally with a receipt.")
    parser.add_argument("--asset-id")
    parser.add_argument("--plan-id")
    parser.add_argument("--clip-id")
    parser.add_argument("--platform")
    parser.add_argument("--scope", choices=["preview_only", "final_render", "edited_social_export"], default="preview_only")
    parser.add_argument("--notes", default="")
    parser.add_argument("--expires-at", help="Optional ISO timestamp. If omitted, the local audit receipt does not expire.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true", help="Write the approval receipt. Without this, the command is a dry-run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = approve_edited_asset(
        config,
        asset_id=args.asset_id,
        plan_id=args.plan_id,
        clip_id=args.clip_id,
        platform=args.platform,
        scope=args.scope,
        notes=args.notes,
        expires_at=args.expires_at,
        dry_run=not args.write or args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
