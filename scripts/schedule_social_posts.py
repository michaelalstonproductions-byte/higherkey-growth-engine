#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.social_scheduler import schedule_posts


def parser() -> argparse.ArgumentParser:
    argp = argparse.ArgumentParser(description="Schedule local social post drafts.")
    argp.add_argument("--clip-id")
    argp.add_argument("--platform")
    argp.add_argument("--when", dest="when")
    argp.add_argument("--caption")
    argp.add_argument("--from-drafts", action="store_true")
    argp.add_argument("--dry-run", action="store_true")
    argp.add_argument("--publish-mode", choices=["manual", "dry_run", "live_api"])
    argp.add_argument("--approval-required", action="store_true")
    argp.add_argument("--no-approval-required", action="store_true")
    argp.add_argument("--json", action="store_true")
    return argp


def main() -> None:
    args = parser().parse_args()
    config = load_config(Path.cwd())
    payload = schedule_posts(
        config,
        clip_id=args.clip_id,
        platform=args.platform,
        when=args.when,
        caption=args.caption,
        from_drafts=args.from_drafts,
        dry_run=args.dry_run or True,
        publish_mode=args.publish_mode,
        approval_required=False if args.no_approval_required else True if args.approval_required else None,
    )
    summary = {
        "status": "pass",
        "scheduled_count": payload.get("count", 0),
        "created_count": payload.get("created_count", 0),
        "updated_count": payload.get("updated_count", 0),
        "changed_count": payload.get("changed_count", 0),
        "paths": [
            "analytics/social_schedule.json",
            "analytics/social_post_queue.json",
            "analytics/post_composer_drafts.json",
        ],
        "dry_run": True,
        "manual_upload_fallback": True,
    }
    print(json.dumps(summary if args.json else payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
