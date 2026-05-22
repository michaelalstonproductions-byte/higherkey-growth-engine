from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file
from .social_exports import PLATFORM_KEYS


STATUSES = {
    "draft",
    "scheduled",
    "ready_to_post",
    "posting",
    "posted",
    "failed",
    "cancelled",
    "manual_upload_required",
    "auth_required",
    "approval_required",
    "scheduled_not_due",
    "unsupported_platform",
}

SUPPORTED_LIVE_PLATFORMS = {"instagram_reels", "tiktok"}


def _list_payload(path: Path, key: str) -> list[dict[str, Any]]:
    payload = load_json_file(path, default={key: []})
    value = payload.get(key, [])
    return value if isinstance(value, list) else []


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _package_caption(root: Path, package_path: str | None) -> dict[str, Any]:
    if not package_path:
        return {}
    return load_json_file(root / package_path, default={})


def _existing_drafts(config: AppConfig) -> dict[str, dict[str, Any]]:
    drafts = _list_payload(config.analytics_dir / "post_composer_drafts.json", "drafts")
    return {str(item.get("draft_id")): item for item in drafts if isinstance(item, dict)}


def _manifest_exports(config: AppConfig) -> list[dict[str, Any]]:
    manifest = load_json_file(config.root / "out" / "social_exports" / "manifest.json", default={"exports": []})
    exports = manifest.get("exports", [])
    return exports if isinstance(exports, list) else []


def _queue_entries(config: AppConfig) -> list[dict[str, Any]]:
    queue = load_json_file(config.queue_dir / "review_queue.json", default={"entries": []})
    entries = queue.get("entries", []) if isinstance(queue, dict) else []
    return entries if isinstance(entries, list) else []


def _entry_for_clip(config: AppConfig, clip_id: str | None) -> dict[str, Any]:
    if not clip_id:
        return {}
    for entry in _queue_entries(config):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("clip_id") or "") == str(clip_id) or str(entry.get("id") or "") == str(clip_id):
            return entry
    return {}


def _export_for_clip(config: AppConfig, platform: str, clip_id: str | None) -> dict[str, Any]:
    if not clip_id:
        return {}
    for item in _manifest_exports(config):
        if isinstance(item, dict) and str(item.get("platform")) == str(platform) and str(item.get("clip_id")) == str(clip_id):
            return item
    return {}


def _new_draft(config: AppConfig, *, clip_id: str, platform: str, caption: str | None = None, when: str | None = None, publish_mode: str = "manual") -> dict[str, Any]:
    entry = _entry_for_clip(config, clip_id)
    export = _export_for_clip(config, platform, clip_id)
    package = _package_caption(config.root, export.get("source_package_path") or entry.get("package_path"))
    generated_caption = (
        _read_text(config.root / str(export.get("caption_txt", "")))
        or package.get("caption")
        or ""
    )
    hashtags_text = _read_text(config.root / str(export.get("hashtags_txt", "")))
    hashtags = [tag for tag in hashtags_text.split() if tag] or package.get("hashtags", [])
    return {
        "draft_id": f"{platform}_{clip_id}",
        "clip_id": clip_id,
        "queue_id": entry.get("id") or f"queue_{clip_id}",
        "platform": platform,
        "video_path": export.get("video") or entry.get("clip_path") or "",
        "thumbnail_path": export.get("thumbnail_jpg") or entry.get("thumbnail_path") or "",
        "package_path": export.get("source_package_path") or entry.get("package_path") or "",
        "generated_caption": generated_caption,
        "user_caption_override": caption or "",
        "user_post_text": caption or "",
        "hashtags": hashtags if isinstance(hashtags, list) else [],
        "title": _read_text(config.root / str(export.get("title_txt", ""))) or package.get("suggested_title") or package.get("hook") or clip_id,
        "CTA": package.get("cta") or "Watch, save, and share if this helps.",
        "scheduled_for": when,
        "timezone": "local",
        "status": "scheduled" if when else "draft",
        "approval_required": True,
        "publish_mode": publish_mode if publish_mode in {"manual", "dry_run", "live_api"} else "manual",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def build_post_composer_drafts(config: AppConfig) -> dict[str, Any]:
    queue = load_json_file(config.queue_dir / "review_queue.json", default={"entries": []})
    approvals = load_json_file(config.queue_dir / "approved_reviews.json", default={})
    approved_ids = set()
    for item in (approvals.get("approved_ids", []) if isinstance(approvals, dict) else []):
        approved_ids.add(str(item))
    for item in (approvals.get("entries", []) if isinstance(approvals, dict) else []):
        if isinstance(item, dict):
            approved_ids.add(str(item.get("clip_id") or item.get("id")))
    exports = _manifest_exports(config)
    export_by_key = {(str(item.get("platform")), str(item.get("clip_id"))): item for item in exports if isinstance(item, dict)}
    existing = _existing_drafts(config)
    drafts: list[dict[str, Any]] = []
    entries = queue.get("entries", []) if isinstance(queue.get("entries"), list) else []
    for entry in entries:
        clip_id = str(entry.get("clip_id") or "")
        entry_id = str(entry.get("id") or f"queue_{clip_id}")
        approved = clip_id in approved_ids or entry_id in approved_ids or entry.get("status") == "approved"
        if not approved:
            continue
        package = _package_caption(config.root, entry.get("package_path"))
        for platform in PLATFORM_KEYS:
            export = export_by_key.get((platform, clip_id), {})
            draft_id = f"{platform}_{clip_id}"
            old = existing.get(draft_id, {})
            generated_caption = (
                _read_text(config.root / str(export.get("caption_txt", "")))
                or package.get("caption")
                or entry.get("caption", {}).get("caption")
                or ""
            )
            hashtags_text = _read_text(config.root / str(export.get("hashtags_txt", "")))
            hashtags = [tag for tag in hashtags_text.split() if tag] or package.get("hashtags", [])
            title = _read_text(config.root / str(export.get("title_txt", ""))) or package.get("suggested_title") or package.get("hook") or clip_id
            video_path = export.get("video") or entry.get("clip_path")
            draft = {
                "draft_id": draft_id,
                "clip_id": clip_id,
                "queue_id": entry_id,
                "platform": platform,
                "video_path": video_path,
                "thumbnail_path": export.get("thumbnail_jpg") or entry.get("thumbnail_path"),
                "package_path": export.get("source_package_path") or entry.get("package_path"),
                "generated_caption": generated_caption,
                "user_caption_override": old.get("user_caption_override", ""),
                "user_post_text": old.get("user_post_text", ""),
                "hashtags": hashtags if isinstance(hashtags, list) else [],
                "title": old.get("title") or title,
                "CTA": old.get("CTA") or package.get("cta") or "Watch, save, and share if this helps.",
                "scheduled_for": old.get("scheduled_for"),
                "timezone": old.get("timezone") or "local",
                "status": old.get("status") or "draft",
                "approval_required": old.get("approval_required", True),
                "publish_mode": old.get("publish_mode") or "manual",
                "created_at": old.get("created_at") or utc_now(),
                "updated_at": utc_now(),
            }
            drafts.append(draft)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "live_api_default": False,
        "count": len(drafts),
        "drafts": drafts,
    }
    save_json_file(config.analytics_dir / "post_composer_drafts.json", payload)
    return payload


def load_drafts(config: AppConfig) -> list[dict[str, Any]]:
    return _list_payload(config.analytics_dir / "post_composer_drafts.json", "drafts")


def save_drafts(config: AppConfig, drafts: list[dict[str, Any]]) -> None:
    save_json_file(config.analytics_dir / "post_composer_drafts.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "count": len(drafts),
        "drafts": drafts,
    })


def schedule_posts(
    config: AppConfig,
    *,
    clip_id: str | None = None,
    platform: str | None = None,
    when: str | None = None,
    caption: str | None = None,
    from_drafts: bool = False,
    dry_run: bool = True,
    publish_mode: str | None = None,
    approval_required: bool | None = None,
) -> dict[str, Any]:
    if from_drafts and not (config.analytics_dir / "post_composer_drafts.json").exists():
        build_post_composer_drafts(config)
    drafts = load_drafts(config)
    selected: list[dict[str, Any]] = []
    target_platform = platform or "manual"
    for draft in drafts:
        if clip_id and draft.get("clip_id") != clip_id and draft.get("draft_id") != clip_id:
            continue
        if platform and draft.get("platform") != platform:
            continue
        selected.append(draft)
    created_count = 0
    updated_count = 0
    if not selected and clip_id and platform:
        mode = publish_mode or ("dry_run" if dry_run else "manual")
        selected = [_new_draft(config, clip_id=clip_id, platform=target_platform, caption=caption, when=when, publish_mode=mode)]
        drafts.extend(selected)
        created_count = 1
    elif not selected and not from_drafts:
        mode = publish_mode or ("dry_run" if dry_run else "manual")
        selected = [_new_draft(config, clip_id=clip_id or "draft", platform=target_platform, caption=caption, when=when, publish_mode=mode)]
        drafts.extend(selected)
        created_count = 1
    schedule_items = []
    for draft in selected:
        before = dict(draft)
        if caption is not None:
            draft["user_post_text"] = caption
            draft["user_caption_override"] = caption
        if publish_mode in {"manual", "dry_run", "live_api"}:
            draft["publish_mode"] = publish_mode
        elif dry_run:
            draft["publish_mode"] = "dry_run"
        else:
            draft.setdefault("publish_mode", "manual")
        if approval_required is not None:
            draft["approval_required"] = approval_required
        if when:
            draft["scheduled_for"] = when
            draft["status"] = "scheduled"
        elif draft.get("scheduled_for"):
            draft["status"] = "scheduled"
        else:
            draft["status"] = "approval_required" if draft.get("approval_required", True) else "draft"
        draft["updated_at"] = utc_now()
        if before != draft and created_count == 0:
            updated_count += 1
        schedule_items.append({
            "schedule_id": f"schedule_{draft['draft_id']}",
            "draft_id": draft["draft_id"],
            "clip_id": draft.get("clip_id"),
            "platform": draft.get("platform"),
            "scheduled_for": draft.get("scheduled_for"),
            "status": draft.get("status"),
            "publish_mode": draft.get("publish_mode"),
            "approval_required": draft.get("approval_required", True),
        })
    save_drafts(config, drafts)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "dry_run": dry_run,
        "count": len(schedule_items),
        "created_count": created_count,
        "updated_count": updated_count,
        "changed_count": created_count + updated_count,
        "items": schedule_items,
    }
    save_json_file(config.analytics_dir / "social_schedule.json", payload)
    save_json_file(config.analytics_dir / "client_social_schedule.json", payload)
    queue_items = []
    for item in schedule_items:
        queued = item | {"status": "ready_to_post" if not item.get("scheduled_for") else item.get("status")}
        if queued.get("publish_mode") == "live_api" and queued.get("platform") not in SUPPORTED_LIVE_PLATFORMS:
            queued["status"] = "manual_upload_required"
            queued["live_publish_eligible"] = False
            queued["blocked_reason"] = "Unsupported live platform; manual upload fallback is required."
        elif queued.get("publish_mode") == "live_api":
            queued["live_publish_eligible"] = queued.get("status") in {"ready_to_post", "scheduled"}
        queue_items.append(queued)
    save_json_file(config.analytics_dir / "social_post_queue.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "count": len(queue_items),
        "items": queue_items,
    })
    history_path = config.analytics_dir / "social_post_history.json"
    history = load_json_file(history_path, default={"items": []})
    history_items = history.get("items", []) if isinstance(history.get("items"), list) else []
    save_json_file(history_path, {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "items": history_items[-100:],
    })
    return payload


def due_drafts(config: AppConfig, *, due_now: bool = False, platform: str | None = None, draft_id: str | None = None) -> list[dict[str, Any]]:
    drafts = load_drafts(config)
    now = datetime.now(timezone.utc)
    selected = []
    for draft in drafts:
        if platform and draft.get("platform") != platform:
            continue
        if draft_id and draft.get("draft_id") != draft_id:
            continue
        if not due_now:
            selected.append(draft)
            continue
        scheduled_for = draft.get("scheduled_for")
        if not scheduled_for:
            selected.append(draft)
            continue
        try:
            scheduled = datetime.fromisoformat(str(scheduled_for).replace("Z", "+00:00"))
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            if scheduled <= now:
                selected.append(draft)
        except ValueError:
            selected.append(draft)
    return selected
