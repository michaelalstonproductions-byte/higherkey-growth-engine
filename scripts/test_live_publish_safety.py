#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file
from growth_engine.live_publish_readiness import CONFIRMATION_PHRASE, create_live_publish_receipt, validate_live_publish_conditions
from growth_engine.social_publisher import publish_drafts


def write_drafts(root: Path, drafts: list[dict]) -> None:
    save_json_file(root / "analytics" / "post_composer_drafts.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "count": len(drafts),
        "drafts": drafts,
    })


def draft(draft_id: str, platform: str, scheduled_for: str) -> dict:
    return {
        "draft_id": draft_id,
        "clip_id": draft_id,
        "queue_id": f"queue_{draft_id}",
        "platform": platform,
        "video_path": "clips/live_fixture.mp4",
        "thumbnail_path": "",
        "package_path": "",
        "generated_caption": "fixture caption",
        "user_caption_override": "fixture caption",
        "user_post_text": "fixture caption",
        "hashtags": [],
        "title": "fixture",
        "CTA": "Watch",
        "scheduled_for": scheduled_for,
        "timezone": "UTC",
        "status": "scheduled",
        "approval_required": True,
        "publish_mode": "live_api",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="higherkey_live_publish_", dir="/private/tmp") as tmp:
        root = Path(tmp)
        for name in ("analytics", "config", "clips", "queue"):
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "config" / "social_connectors.example.json", root / "config" / "social_connectors.example.json")
        shutil.copy2(ROOT / "config" / "live_publish_policy.example.json", root / "config" / "live_publish_policy.example.json")
        (root / "clips" / "live_fixture.mp4").write_bytes(b"fixture")
        config = load_config(root)

        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        due = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        write_drafts(root, [
            draft("future_tiktok", "tiktok", future),
            draft("due_youtube", "youtube_shorts", due),
            draft("due_tiktok", "tiktok", due),
        ])

        future_readiness = validate_live_publish_conditions(config, draft_id="future_tiktok", platform="tiktok", require_receipt=False)
        assert future_readiness["status"] == "scheduled_not_due", future_readiness
        unsupported = validate_live_publish_conditions(config, draft_id="due_youtube", platform="youtube_shorts", require_receipt=False)
        assert unsupported["status"] == "unsupported_platform", unsupported
        no_receipt = validate_live_publish_conditions(config, draft_id="due_tiktok", platform="tiktok", require_receipt=True)
        assert any(item.get("status") == "approval_required" for item in no_receipt.get("reasons", [])), no_receipt
        bad_receipt = create_live_publish_receipt(config, draft_id="due_tiktok", platform="tiktok", confirmation_phrase="wrong")
        assert bad_receipt["valid"] is False and bad_receipt["status"] == "approval_required", bad_receipt
        good_receipt = create_live_publish_receipt(config, draft_id="due_tiktok", platform="tiktok", confirmation_phrase=CONFIRMATION_PHRASE, dry_run_before_live=True)
        assert good_receipt["valid"] is True, good_receipt
        bulk = publish_drafts(config, live=True, approve=True)
        assert bulk["live_call_made"] is False
        assert bulk["results"][0]["status"] == "blocked", bulk
        sandbox = publish_drafts(config, dry_run=True, live=True, live_sandbox=True, due_now=True)
        assert sandbox["live_call_made"] is False, sandbox

    print(json.dumps({
        "status": "pass",
        "future_draft_blocked": True,
        "unsupported_platform_blocked": True,
        "bulk_live_blocked": True,
        "confirmation_phrase_required": True,
        "receipt_required": True,
        "live_call_made": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
