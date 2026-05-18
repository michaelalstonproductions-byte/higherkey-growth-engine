#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from growth_engine.performance_feedback import record_post_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Record local manual post performance results.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--posted-at", default=None)
    parser.add_argument("--views", type=float, default=0)
    parser.add_argument("--likes", type=float, default=0)
    parser.add_argument("--comments", type=float, default=0)
    parser.add_argument("--shares", type=float, default=0)
    parser.add_argument("--saves", type=float, default=0)
    parser.add_argument("--watch-time", type=float, default=0)
    parser.add_argument("--retention", type=float, default=0)
    parser.add_argument("--profile-visits", type=float, default=0)
    parser.add_argument("--follows", type=float, default=0)
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    values = {
        "clip_id": args.clip_id,
        "platform": args.platform,
        "posted_at": args.posted_at,
        "views": args.views,
        "likes": args.likes,
        "comments": args.comments,
        "shares": args.shares,
        "saves": args.saves,
        "watch_time": args.watch_time,
        "retention": args.retention,
        "profile_visits": args.profile_visits,
        "follows": args.follows,
        "notes": args.notes,
    }
    result = record_post_result(Path(args.root), values, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
