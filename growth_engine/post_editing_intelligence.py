from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file
from .media_editor import editing_capabilities


def _analytics(config: AppConfig, name: str) -> Path:
    return config.analytics_dir / name


def _load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_json_file(path, default or {})


def _queue_entries(config: AppConfig) -> list[dict[str, Any]]:
    payload = _load(config.queue_dir / "review_queue.json", {"entries": []})
    entries = payload.get("entries") or payload.get("items") or []
    return entries if isinstance(entries, list) else []


def _approved(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved = [entry for entry in entries if str(entry.get("status") or entry.get("review_status") or "").lower() == "approved"]
    return approved or entries[:6]


def _suggestions(entry: dict[str, Any], notes: str = "") -> list[dict[str, Any]]:
    base = [
        ("crop_to_9_16", "Create a vertical safe-frame version for Reels, TikTok, Shorts, and Facebook Reels."),
        ("trim_start_end", "Trim dead air and keep the strongest hook-to-payoff sequence."),
        ("caption_overlay", "Add readable captions with high contrast and safe margins."),
        ("title_card", "Add an optional first-frame title if the hook needs context."),
        ("cta_end_card", "End with a simple manual-upload CTA."),
        ("color_boost", "Apply a subtle brightness, contrast, and saturation lift."),
        ("audio_normalize", "Normalize dialogue/music for local social preview review."),
        ("silence_trim", "Suggest silence trims without destructively changing source media."),
        ("thumbnail_frame", "Select a high-contrast frame for thumbnail concepts."),
        ("platform_versions", "Prepare platform-specific local render jobs."),
    ]
    if notes:
        base.insert(0, ("user_notes", f"Respect user edit note: {notes[:160]}"))
    return [{"id": key, "label": label, "destructive": False, "requires_approval": key in {"cta_end_card", "platform_versions"}} for key, label in base]


def build_post_editing_recommendations(config: AppConfig, *, notes: str = "", limit: int = 8) -> dict[str, Any]:
    entries = _approved(_queue_entries(config))[:limit]
    creative = _load(_analytics(config, "creative_director_brief.json"), {})
    campaign = _load(_analytics(config, "client_campaign_plan.json"), {})
    color = _load(_analytics(config, "color_school_report.json"), {})
    audio = _load(_analytics(config, "audio_school_report.json"), {})
    manifest = _load(config.root / "out" / "social_exports" / "manifest.json", {"exports": []})
    recommendations = []
    for entry in entries:
        recommendations.append(
            {
                "clip_id": entry.get("clip_id") or entry.get("id"),
                "title": entry.get("title") or entry.get("clip_id") or "Local clip",
                "source_path": entry.get("clip_path") or entry.get("video_path") or entry.get("source_path"),
                "score": entry.get("score"),
                "suggestions": _suggestions(entry, notes),
                "creative_direction": creative.get("creative_thesis") or creative.get("summary") or "Use the strongest local hook and clear caption overlay.",
                "campaign_context": campaign.get("primary_goal") or campaign.get("summary") or "Prepare a platform-ready social asset.",
                "color_reference": color.get("status") or "local color report pending",
                "audio_reference": audio.get("status") or "local audio report pending",
            }
        )
    payload = {
        "status": "pass",
        "updated_at": utc_now(),
        "local_only": True,
        "cloud_editing_api_enabled": False,
        "non_destructive": True,
        "manual_upload_fallback": True,
        "inputs": {
            "queue_entries": len(entries),
            "social_export_count": len(manifest.get("exports", []) if isinstance(manifest.get("exports"), list) else []),
            "user_notes_present": bool(notes),
        },
        "recommendations": recommendations,
    }
    client = {
        "status": payload["status"],
        "updated_at": payload["updated_at"],
        "headline": "AI Post Editing Studio is ready locally.",
        "non_destructive": True,
        "original_media_protected": True,
        "cloud_editing_api_enabled": False,
        "recommendations": recommendations[:5],
        "capabilities": editing_capabilities(config),
    }
    save_json_file(_analytics(config, "post_editing_recommendations.json"), payload)
    save_json_file(_analytics(config, "client_post_editing_plan.json"), client)
    return payload
