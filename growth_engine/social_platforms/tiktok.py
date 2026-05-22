from __future__ import annotations

from pathlib import Path
from typing import Any


class TikTokAdapter:
    platform = "tiktok"
    label = "TikTok"

    def prepare_payload(self, draft: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        caption = draft.get("user_post_text") or draft.get("user_caption_override") or draft.get("generated_caption") or ""
        privacy = draft.get("privacy_level") or "SELF_ONLY"
        return {
            "platform": self.platform,
            "mode": "official_api",
            "dry_run_only_by_default": True,
            "requires_user_authorization": True,
            "requires_explicit_approval": True,
            "required_scopes": config.get("required_scopes", []),
            "privacy_level": privacy,
            "caption": caption,
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_path": draft.get("video_path"),
            },
            "steps": [
                "query_creator_info",
                "initialize_post",
                "upload_video_chunks",
                "check_post_status_if_available",
            ],
            "notes": "Unaudited TikTok clients may be private-post restricted.",
        }

    def validate_media(self, draft: dict[str, Any], root: Path) -> tuple[bool, str | None]:
        video_path = draft.get("video_path")
        if not video_path:
            return False, "Draft is missing video_path."
        if not (root / str(video_path)).exists():
            return False, "Video file does not exist."
        return True, None

    def publish(self, draft: dict[str, Any], config: dict[str, Any], auth: dict[str, Any], root: Path, live: bool = False) -> dict[str, Any]:
        payload = self.prepare_payload(draft, config)
        if not live:
            return {"status": "dry_run", "platform": self.platform, "payload": payload, "live_call_made": False}
        ok, error = self.validate_media(draft, root)
        if not ok:
            return {"status": "manual_upload_required", "platform": self.platform, "error": error, "payload": payload, "live_call_made": False}
        if auth.get("status") != "connected":
            return {"status": "auth_required", "platform": self.platform, "error": "TikTok account is not connected.", "live_call_made": False}
        return {
            "status": "blocked",
            "platform": self.platform,
            "error": "Live TikTok calls are gated until app approval, valid scopes, token storage, and explicit approval are present.",
            "payload": payload,
            "live_call_made": False,
        }
