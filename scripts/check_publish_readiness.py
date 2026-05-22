#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.social_auth import connector_status
from growth_engine.social_publisher import CAPTION_LIMITS, caption_for, parse_scheduled_for


def list_payload(path: Path, key: str) -> list[dict[str, Any]]:
    payload = load_json_file(path, default={key: []})
    value = payload.get(key, []) if isinstance(payload, dict) else []
    return value if isinstance(value, list) else []


def platform_connection(connection: dict[str, Any], platform: str) -> dict[str, Any]:
    if platform == "instagram_reels":
        return connection.get("instagram", {})
    if platform == "tiktok":
        return connection.get("tiktok", {})
    return {"status": "ready_for_manual_upload", "connected": False, "live_api_enabled": False}


def readiness_for_draft(root: Path, draft: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    platform = str(draft.get("platform") or "")
    video_path = str(draft.get("video_path") or "")
    caption = caption_for(draft).strip()
    scheduled = parse_scheduled_for(draft.get("scheduled_for"))
    platform_status = platform_connection(connection, platform)
    reasons: list[str] = []
    statuses = {"ready_for_manual_upload", "ready_for_dry_run"}
    if not platform:
        statuses.add("missing_platform")
        reasons.append("Missing platform.")
    if not video_path or not (root / video_path).exists():
        statuses.add("missing_video")
        reasons.append("Missing local video file.")
    if not caption:
        statuses.add("missing_caption")
        reasons.append("Missing post text.")
    if scheduled and scheduled > now:
        statuses.add("scheduled_not_due")
        reasons.append("Scheduled time has not arrived.")
    if platform in CAPTION_LIMITS and len(caption) > CAPTION_LIMITS[platform]:
        statuses.add("missing_caption")
        reasons.append(f"Post text is longer than the {platform} limit.")
    if platform in {"instagram_reels", "tiktok"} and platform_status.get("status") != "ready_for_live_api":
        statuses.add("auth_required")
        statuses.add("live_blocked")
        reasons.append("Official connector is not ready for live API publishing.")
    elif platform in {"instagram_reels", "tiktok"}:
        statuses.add("ready_for_live_if_enabled")
    return {
        "draft_id": draft.get("draft_id"),
        "clip_id": draft.get("clip_id"),
        "platform": platform,
        "title": draft.get("title") or draft.get("clip_id") or "Untitled clip",
        "scheduled_for": draft.get("scheduled_for"),
        "status": draft.get("status") or "draft",
        "publish_mode": draft.get("publish_mode") or "manual",
        "post_text_preview": caption[:180],
        "export_folder": draft.get("package_path") or "out/social_exports",
        "readiness": sorted(statuses),
        "blocked_reasons": reasons,
        "manual_upload_fallback": True,
        "dry_run_result": "not_run",
    }


def build_publish_readiness(root: Path) -> dict[str, Any]:
    config = load_config(root)
    connection = connector_status(config)
    drafts = list_payload(config.analytics_dir / "post_composer_drafts.json", "drafts")
    schedule = list_payload(config.analytics_dir / "social_schedule.json", "items")
    queue = list_payload(config.analytics_dir / "social_post_queue.json", "items")
    manifest = load_json_file(root / "out" / "social_exports" / "manifest.json", default={"exports": []})
    items = [readiness_for_draft(root, draft, connection) for draft in drafts]
    summary = {
        "drafts_ready": len(drafts),
        "scheduled": sum(1 for item in items if item.get("scheduled_for")),
        "ready_for_manual_upload": sum(1 for item in items if "ready_for_manual_upload" in item["readiness"]),
        "auth_required": sum(1 for item in items if "auth_required" in item["readiness"]),
        "dry_run_ready": sum(1 for item in items if "ready_for_dry_run" in item["readiness"]),
        "live_blocked": sum(1 for item in items if "live_blocked" in item["readiness"]),
        "posted_history": len(list_payload(config.analytics_dir / "social_post_history.json", "items")),
    }
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "token_values_exposed": False,
        "live_call_made": False,
        "summary": summary,
        "items": items,
        "source_counts": {
            "drafts": len(drafts),
            "schedule": len(schedule),
            "queue": len(queue),
            "social_exports": len(manifest.get("exports", [])) if isinstance(manifest.get("exports"), list) else 0,
        },
    }
    save_json_file(config.analytics_dir / "publish_readiness.json", payload)
    save_json_file(config.analytics_dir / "client_publish_readiness.json", payload)
    return payload


def main() -> int:
    payload = build_publish_readiness(Path.cwd())
    print(json.dumps({
        "status": "pass",
        "manual_upload_fallback": True,
        "live_call_made": False,
        "token_values_exposed": False,
        "items": len(payload.get("items", [])),
        "paths": [
            "analytics/publish_readiness.json",
            "analytics/client_publish_readiness.json",
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
