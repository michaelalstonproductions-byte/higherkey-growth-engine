from __future__ import annotations

from pathlib import Path
from typing import Any


class InstagramAdapter:
    platform = "instagram_reels"
    label = "Instagram Reels"

    def prepare_payload(self, draft: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        caption = draft.get("user_post_text") or draft.get("user_caption_override") or draft.get("generated_caption") or ""
        media_url = draft.get("media_url") or draft.get("hosted_media_url")
        return {
            "platform": self.platform,
            "mode": "official_api",
            "dry_run_only_by_default": True,
            "requires_user_authorization": True,
            "requires_explicit_approval": True,
            "media_type": "REELS",
            "caption": caption,
            "media_url": media_url,
            "creation_container": {
                "ig_user_id": "<instagram_business_account_id>",
                "media_type": "REELS",
                "video_url": media_url or "<hosted_video_url_required>",
                "caption": caption,
            },
            "publish_container": {
                "ig_user_id": "<instagram_business_account_id>",
                "creation_id": "<creation_container_id>",
            },
            "required_permissions": config.get("required_permissions", []),
        }

    def validate_media(self, draft: dict[str, Any], root: Path) -> tuple[bool, str | None]:
        video_path = draft.get("video_path")
        if not video_path:
            return False, "Draft is missing video_path."
        if not (root / str(video_path)).exists():
            return False, "Video file does not exist."
        if not (draft.get("media_url") or draft.get("hosted_media_url")):
            return False, "Instagram publishing requires hosted media or resumable upload support."
        return True, None

    def publish(self, draft: dict[str, Any], config: dict[str, Any], auth: dict[str, Any], root: Path, live: bool = False) -> dict[str, Any]:
        payload = self.prepare_payload(draft, config)
        if not live:
            return {"status": "dry_run", "platform": self.platform, "payload": payload, "live_call_made": False}
        return perform_instagram_live_publish(draft, config, auth, root, payload=payload)


def perform_instagram_live_publish(draft: dict[str, Any], config: dict[str, Any], auth: dict[str, Any], root: Path, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    adapter = InstagramAdapter()
    payload = payload or adapter.prepare_payload(draft, config)
    ok, error = adapter.validate_media(draft, root)
    if not ok:
        return {"status": "manual_upload_required", "platform": adapter.platform, "error": error, "payload": payload, "live_call_made": False}
    if auth.get("status") not in {"connected", "ready_for_live_api"}:
        return {"status": "auth_required", "platform": adapter.platform, "error": "Instagram account is not connected.", "live_call_made": False}
    return {
        "status": "live_publish_not_fully_supported",
        "platform": adapter.platform,
        "error": "Official Instagram readiness passed, but live publish execution is not enabled in this build.",
        "payload": payload,
        "manual_upload_fallback": True,
        "live_call_made": False,
    }
