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
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.live_publish_readiness import CONFIRMATION_PHRASE, create_live_publish_receipt
from growth_engine.social_publisher import publish_drafts


def parser() -> argparse.ArgumentParser:
    argp = argparse.ArgumentParser(description="Run the local social publisher in dry-run or gated live mode.")
    argp.add_argument("--dry-run", action="store_true", default=True)
    argp.add_argument("--live", action="store_true")
    argp.add_argument("--live-single", action="store_true")
    argp.add_argument("--live-sandbox", action="store_true")
    argp.add_argument("--due-now", action="store_true")
    argp.add_argument("--platform")
    argp.add_argument("--draft-id")
    argp.add_argument("--approve", action="store_true")
    argp.add_argument("--confirm-live", action="store_true")
    argp.add_argument("--confirmation-phrase", default="")
    argp.add_argument("--json", action="store_true")
    return argp


def main() -> None:
    args = parser().parse_args()
    config = load_config(Path.cwd())
    live_requested = bool(args.live or args.live_single or args.live_sandbox)
    dry_run = not live_requested or args.live_sandbox
    receipt_result = None
    if live_requested and not args.live_sandbox:
        if not args.draft_id:
            receipt_result = {"status": "approval_required", "valid": False, "message": "Live publishing requires --draft-id."}
        elif not args.confirm_live or args.confirmation_phrase != CONFIRMATION_PHRASE:
            receipt_result = {"status": "approval_required", "valid": False, "message": "Live publishing requires --confirm-live and the exact confirmation phrase."}
        elif not args.platform:
            receipt_result = {"status": "approval_required", "valid": False, "message": "Live publishing requires --platform."}
        else:
            receipt_result = create_live_publish_receipt(
                config,
                draft_id=args.draft_id,
                platform=args.platform,
                confirmation_phrase=args.confirmation_phrase,
                dry_run_before_live=True,
            )
        if not receipt_result.get("valid"):
            payload = {
                "version": 1,
                "updated_at": utc_now(),
                "local_only": True,
                "dry_run": False,
                "live_requested": True,
                "approval_present": bool(args.approve),
                "manual_upload_fallback": True,
                "live_call_made": False,
                "count": 1,
                "results": [{
                    "status": receipt_result.get("status", "approval_required"),
                    "message": receipt_result.get("message", "Live publish approval receipt is required."),
                    "live_call_made": False,
                }],
            }
            save_json_file(config.analytics_dir / "social_publisher_status.json", payload)
            save_json_file(config.analytics_dir / "social_live_publish_status.json", payload)
            log_path = config.analytics_dir / "social_live_publish_log.json"
            existing = load_json_file(log_path, default={"runs": []})
            runs = existing.get("runs", []) if isinstance(existing, dict) and isinstance(existing.get("runs"), list) else []
            runs.append(payload)
            save_json_file(log_path, {"version": 1, "updated_at": utc_now(), "local_only": True, "manual_upload_fallback": True, "live_call_made": False, "runs": runs[-100:]})
            result_statuses = {str(item.get("status")) for item in payload.get("results", []) if isinstance(item, dict)}
            status = "blocked" if result_statuses else "warn"
            summary = {
                "status": status,
                "dry_run": payload.get("dry_run"),
                "live_requested": payload.get("live_requested"),
                "live_call_made": payload.get("live_call_made"),
                "publish_count": payload.get("count", 0),
                "receipt": receipt_result,
                "paths": [
                    "analytics/social_live_publish_status.json",
                    "analytics/social_live_publish_log.json",
                    "analytics/live_publish_receipts.json",
                ],
                "manual_upload_fallback": True,
            }
            print(json.dumps(summary if args.json else payload, indent=2, sort_keys=True))
            return
    payload = publish_drafts(
        config,
        dry_run=dry_run,
        live=live_requested,
        live_single=args.live_single,
        live_sandbox=args.live_sandbox,
        due_now=args.due_now,
        platform=args.platform,
        draft_id=args.draft_id,
        approve=args.approve,
        receipt_id=receipt_result.get("receipt", {}).get("receipt_id") if isinstance(receipt_result, dict) else None,
    )
    result_statuses = {str(item.get("status")) for item in payload.get("results", []) if isinstance(item, dict)}
    blocked_statuses = {"auth_required", "approval_required", "scheduled_not_due", "manual_upload_required", "blocked", "failed"}
    if payload.get("live_call_made") is True:
        status = "fail"
    elif live_requested and result_statuses.intersection(blocked_statuses):
        status = "blocked"
    elif live_requested:
        status = "warn"
    else:
        status = "pass"
    summary = {
        "status": status,
        "dry_run": payload.get("dry_run"),
        "live_requested": payload.get("live_requested"),
        "live_call_made": payload.get("live_call_made"),
        "publish_count": payload.get("count", 0),
        "receipt": receipt_result,
        "paths": [
            "analytics/social_publisher_status.json",
            "analytics/social_publish_log.json",
            "analytics/social_publish_errors.json",
            "analytics/social_live_publish_status.json",
            "analytics/social_live_publish_log.json",
        ],
        "manual_upload_fallback": True,
    }
    print(json.dumps(summary if args.json else payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
