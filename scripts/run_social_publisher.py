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
from growth_engine.social_publisher import publish_drafts


def parser() -> argparse.ArgumentParser:
    argp = argparse.ArgumentParser(description="Run the local social publisher in dry-run or gated live mode.")
    argp.add_argument("--dry-run", action="store_true", default=True)
    argp.add_argument("--live", action="store_true")
    argp.add_argument("--due-now", action="store_true")
    argp.add_argument("--platform")
    argp.add_argument("--draft-id")
    argp.add_argument("--approve", action="store_true")
    argp.add_argument("--json", action="store_true")
    return argp


def main() -> None:
    args = parser().parse_args()
    config = load_config(Path.cwd())
    dry_run = not args.live
    payload = publish_drafts(
        config,
        dry_run=dry_run,
        live=args.live,
        due_now=args.due_now,
        platform=args.platform,
        draft_id=args.draft_id,
        approve=args.approve,
    )
    result_statuses = {str(item.get("status")) for item in payload.get("results", []) if isinstance(item, dict)}
    blocked_statuses = {"auth_required", "approval_required", "scheduled_not_due", "manual_upload_required", "blocked", "failed"}
    if payload.get("live_call_made") is True:
        status = "fail"
    elif args.live and result_statuses.intersection(blocked_statuses):
        status = "blocked"
    elif args.live:
        status = "warn"
    else:
        status = "pass"
    summary = {
        "status": status,
        "dry_run": payload.get("dry_run"),
        "live_requested": payload.get("live_requested"),
        "live_call_made": payload.get("live_call_made"),
        "publish_count": payload.get("count", 0),
        "paths": [
            "analytics/social_publisher_status.json",
            "analytics/social_publish_log.json",
            "analytics/social_publish_errors.json",
        ],
        "manual_upload_fallback": True,
    }
    print(json.dumps(summary if args.json else payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
