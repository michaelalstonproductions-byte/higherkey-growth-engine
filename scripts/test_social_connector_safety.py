#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.social_publisher import publish_drafts
from growth_engine.social_scheduler import schedule_posts
from growth_engine.social_token_vault import vault_status


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="higherkey_social_safety_", dir="/private/tmp") as tmp:
        root = Path(tmp)
        for name in ("analytics", "config", "queue", "clips"):
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "config" / "social_connectors.example.json", root / "config" / "social_connectors.example.json")
        clip_path = root / "clips" / "clip_001.mp4"
        clip_path.write_bytes(b"placeholder video bytes")
        write_json(root / "queue" / "review_queue.json", {
            "entries": [{
                "id": "queue_clip_001",
                "clip_id": "clip_001",
                "clip_path": "clips/clip_001.mp4",
                "package_path": "",
                "status": "approved",
            }]
        })
        write_json(root / "analytics" / "post_composer_drafts.json", {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "local_only": True,
            "manual_upload_fallback": True,
            "count": 0,
            "drafts": [],
        })
        config = load_config(root)
        save = schedule_posts(
            config,
            clip_id="clip_001",
            platform="tiktok",
            caption="User-written post text",
            from_drafts=True,
            dry_run=True,
            publish_mode="live_api",
            approval_required=True,
        )
        drafts = json.loads((root / "analytics" / "post_composer_drafts.json").read_text(encoding="utf-8"))["drafts"]
        assert save["created_count"] == 1, save
        assert save["changed_count"] == 1, save
        assert drafts[0]["user_post_text"] == "User-written post text", drafts[0]
        assert drafts[0]["user_caption_override"] == "User-written post text", drafts[0]

        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        scheduled = schedule_posts(
            config,
            clip_id="clip_001",
            platform="tiktok",
            when=future,
            caption="Future post text",
            from_drafts=True,
            dry_run=False,
            publish_mode="live_api",
            approval_required=True,
        )
        assert scheduled["updated_count"] == 1, scheduled
        result = publish_drafts(config, dry_run=False, live=True, due_now=False, platform="tiktok", approve=True)
        statuses = {item.get("status") for item in result["results"]}
        assert "scheduled_not_due" in statuses, result
        assert result["live_call_made"] is False, result
        due = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        schedule_posts(
            config,
            clip_id="clip_001",
            platform="tiktok",
            when=due,
            caption="Due post text",
            from_drafts=True,
            dry_run=False,
            publish_mode="live_api",
            approval_required=True,
        )
        bulk_result = publish_drafts(config, dry_run=False, live=True, due_now=False, platform="tiktok", approve=True)
        bulk_statuses = {item.get("status") for item in bulk_result["results"]}
        assert "blocked" in bulk_statuses, bulk_result
        assert bulk_result["live_call_made"] is False, bulk_result
        vault = vault_status(config)
        assert vault["token_values_exposed"] is False, vault
        assert "tokens" in vault and vault["tokens"]["tiktok"]["token_preview"] in {"", "redacted"}, vault

    print(json.dumps({
        "status": "pass",
        "save_draft_upsert": True,
        "future_live_blocked": True,
        "bulk_live_without_due_now_blocked": True,
        "token_vault_redacted": True,
        "live_call_made": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
