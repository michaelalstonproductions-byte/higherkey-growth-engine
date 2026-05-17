#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.campaign_planner import MANUAL_STATUSES, update_manual_post_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Track manual upload status for a campaign card.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--clip-id", required=True, help="Clip ID to update.")
    parser.add_argument("--platform", required=True, help="Platform key, e.g. tiktok or instagram_reels.")
    parser.add_argument("--status", required=True, choices=sorted(MANUAL_STATUSES), help="Manual post status.")
    parser.add_argument("--notes", default="", help="Operator notes.")
    args = parser.parse_args()
    result = update_manual_post_status(
        Path(args.root).resolve(),
        clip_id=args.clip_id,
        platform=args.platform,
        status=args.status,
        notes=args.notes,
    )
    record = result["posts"][f"{args.platform.strip().lower()}:{args.clip_id}"]
    print(json.dumps({
        "ok": True,
        "local_only": True,
        "manual_tracking_only": True,
        "direct_posting_apis": False,
        "record": record,
        "output": "analytics/manual_post_status.json",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
