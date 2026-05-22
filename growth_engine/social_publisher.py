from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .social_auth import check_social_auth_status, load_connector_config
from .social_platforms import InstagramAdapter, TikTokAdapter
from .social_scheduler import due_drafts


ADAPTERS = {
    "instagram_reels": InstagramAdapter(),
    "tiktok": TikTokAdapter(),
}

CAPTION_LIMITS = {
    "instagram_reels": 2200,
    "tiktok": 2200,
    "youtube_shorts": 5000,
    "facebook_reels": 63206,
}


def caption_for(draft: dict[str, Any]) -> str:
    return str(draft.get("user_post_text") or draft.get("user_caption_override") or draft.get("generated_caption") or "")


def validate_draft(config: AppConfig, draft: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    platform = str(draft.get("platform") or "")
    video_path = draft.get("video_path")
    if not video_path:
        errors.append("Draft is missing video_path.")
    elif not (config.root / str(video_path)).exists():
        errors.append("Video file does not exist.")
    limit = CAPTION_LIMITS.get(platform, 2200)
    if len(caption_for(draft)) > limit:
        errors.append(f"Caption is longer than the {platform} limit of {limit} characters.")
    if platform not in CAPTION_LIMITS:
        errors.append("Unsupported platform.")
    return errors


def parse_scheduled_for(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def live_due_status(draft: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    scheduled = parse_scheduled_for(draft.get("scheduled_for"))
    if not scheduled:
        return {
            "draft_id": draft.get("draft_id"),
            "platform": draft.get("platform"),
            "status": "approval_required",
            "message": "Live publishing requires a scheduled time that is due now.",
            "live_call_made": False,
        }
    if scheduled > now:
        return {
            "draft_id": draft.get("draft_id"),
            "platform": draft.get("platform"),
            "status": "scheduled_not_due",
            "message": "This post is scheduled for later and will not publish now.",
            "scheduled_for": draft.get("scheduled_for"),
            "live_call_made": False,
        }
    return None


def publish_drafts(config: AppConfig, *, dry_run: bool = True, live: bool = False, due_now: bool = False, platform: str | None = None, draft_id: str | None = None, approve: bool = False) -> dict[str, Any]:
    connectors = load_connector_config(config.root)
    auth_status = check_social_auth_status(config)
    selected = due_drafts(config, due_now=False if live else due_now, platform=platform, draft_id=draft_id)
    results = []
    live_call_made = False
    now = datetime.now(timezone.utc)
    for draft in selected:
        draft_platform = str(draft.get("platform") or "")
        if live:
            due_result = live_due_status(draft, now)
            if due_result:
                results.append(due_result)
                continue
            if not due_now and not draft_id:
                results.append({
                    "draft_id": draft.get("draft_id"),
                    "platform": draft_platform,
                    "status": "blocked",
                    "message": "Live publishing requires a specific draft or the due-now publisher path.",
                    "live_call_made": False,
                })
                continue
        errors = validate_draft(config, draft)
        mode = draft.get("publish_mode") or "manual"
        if live and not approve:
            errors.append("Live publishing requires explicit user approval.")
        if live and mode != "live_api":
            errors.append("Draft publish_mode is not live_api.")
        if errors:
            results.append({
                "draft_id": draft.get("draft_id"),
                "platform": draft_platform,
                "status": "manual_upload_required" if "Video file does not exist." in errors else "failed",
                "errors": errors,
                "live_call_made": False,
            })
            continue
        if draft_platform in ADAPTERS:
            platform_key = "instagram" if draft_platform == "instagram_reels" else draft_platform
            platform_config = connectors.get(platform_key, {})
            platform_auth = auth_status.get(platform_key, {})
            enabled = platform_config.get("enabled") is True
            live_enabled = platform_config.get("live_api_enabled") is True
            if live and (not enabled or not live_enabled or platform_auth.get("status") != "connected"):
                result = {
                    "draft_id": draft.get("draft_id"),
                    "platform": draft_platform,
                    "status": "auth_required",
                    "errors": ["Official connector is not enabled, live mode is disabled, or authorization is required."],
                    "manual_upload_fallback": True,
                    "live_call_made": False,
                }
            else:
                result = ADAPTERS[draft_platform].publish(draft, platform_config, platform_auth, config.root, live=bool(live and not dry_run))
                result["draft_id"] = draft.get("draft_id")
        else:
            result = {
                "draft_id": draft.get("draft_id"),
                "platform": draft_platform,
                "status": "manual_upload_required" if live else "dry_run",
                "message": "Manual upload fallback is available for this platform.",
                "live_call_made": False,
            }
        live_call_made = live_call_made or bool(result.get("live_call_made"))
        results.append(result)
    status = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "dry_run": dry_run or not live,
        "live_requested": live,
        "approval_present": approve,
        "manual_upload_fallback": True,
        "live_call_made": live_call_made,
        "count": len(results),
        "results": results,
    }
    save_json_file(config.analytics_dir / "social_publisher_status.json", status)
    log_path = config.analytics_dir / "social_publish_log.json"
    existing = load_json_file(log_path, default={"runs": []})
    runs = existing.get("runs", []) if isinstance(existing.get("runs"), list) else []
    runs.append(status)
    save_json_file(log_path, {"version": 1, "updated_at": utc_now(), "local_only": True, "runs": runs[-100:]})
    errors = [result for result in results if result.get("status") in {"failed", "auth_required", "manual_upload_required", "blocked", "scheduled_not_due", "approval_required"}]
    save_json_file(config.analytics_dir / "social_publish_errors.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "errors": errors,
    })
    return status
