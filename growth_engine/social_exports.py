from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .exporter import approved_ids
from .index import relative_path, utc_now


PLATFORM_KEYS = ("tiktok", "instagram_reels", "youtube_shorts", "facebook_reels")


def load_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return fallback or {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    path.write_text(str(value or "").rstrip() + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")


def load_presets(root: Path) -> dict[str, Any]:
    presets_path = root / "config" / "social_platform_presets.json"
    return load_json(presets_path, {})


def selected_ids(root: Path, approvals_path: Path | None, approved_id_values: list[str] | None) -> set[str]:
    selected = {str(value) for value in (approved_id_values or []) if str(value).strip()}
    if selected:
        return selected
    approvals_file = approvals_path or root / "queue" / "approved_reviews.json"
    if not approvals_file.exists():
        return set()
    return approved_ids(load_json(approvals_file))


def entry_selected(entry: dict[str, Any], selected: set[str]) -> bool:
    return str(entry.get("id")) in selected or str(entry.get("clip_id")) in selected


def hashtags_for(package: dict[str, Any]) -> list[str]:
    hashtags = package.get("hashtags", [])
    if not isinstance(hashtags, list):
        return []
    return [str(tag) for tag in hashtags if str(tag).strip()]


def media_cache_by_clip(root: Path) -> dict[str, Any]:
    media_cache = load_json(root / "analytics" / "media_cache.json", {})
    clips = media_cache.get("clips", {})
    return clips if isinstance(clips, dict) else {}


def checklist_text(platform_label: str, preset: dict[str, Any]) -> str:
    return "\n".join([
        f"Manual upload checklist for {platform_label}",
        "",
        "[ ] Review the video copy before upload.",
        "[ ] Confirm vertical aspect and framing.",
        "[ ] Paste caption.txt into the platform composer.",
        "[ ] Paste hashtags.txt after the caption if appropriate.",
        "[ ] Use title.txt where the platform supports a title.",
        "[ ] Review posting_notes.txt before publishing.",
        "[ ] Confirm thumbnail if the platform allows manual cover selection.",
        "[ ] Upload manually. No direct posting integration is configured.",
        "",
        f"Aspect: {preset.get('aspect_rules', '')}",
        f"Duration: {preset.get('duration_guidance', '')}",
        f"Title: {preset.get('title_length_guidance', '')}",
        f"Hashtags: {preset.get('hashtag_guidance', '')}",
    ])


def export_social_packs(
    root: Path,
    platforms: list[str] | None = None,
    approvals_path: Path | None = None,
    approved_id_values: list[str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    project_root = root.resolve()
    queue = load_json(project_root / "queue" / "review_queue.json", {"entries": []})
    presets = load_presets(project_root)
    selected = selected_ids(project_root, approvals_path, approved_id_values)
    selected_platforms = platforms or list(PLATFORM_KEYS)
    export_root = output_dir or project_root / "out" / "social_exports"
    media_cache = media_cache_by_clip(project_root)

    export_root.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    exported: list[dict[str, Any]] = []

    if not selected:
        summary = {
            "version": 1,
            "updated_at": utc_now(),
            "local_only": True,
            "manual_upload_only": True,
            "direct_posting_apis": False,
            "count": 0,
            "output_dir": relative_path(export_root, project_root),
            "platforms": selected_platforms,
            "exports": [],
            "errors": [{"error": "No approved IDs supplied and queue/approved_reviews.json was not usable."}],
        }
        (export_root / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary

    for platform in selected_platforms:
        if platform not in PLATFORM_KEYS:
            errors.append({"platform": platform, "error": "Unsupported platform"})
            continue
        preset = presets.get(platform, {})
        platform_label = preset.get("platform_label", platform)
        platform_root = export_root / platform
        platform_root.mkdir(parents=True, exist_ok=True)

        for entry in queue.get("entries", []):
            if not entry_selected(entry, selected):
                continue
            clip_id = entry.get("clip_id")
            clip_path = entry.get("clip_path")
            package_path = entry.get("package_path")
            if not clip_id or not clip_path or not package_path:
                errors.append({"platform": platform, "entry_id": entry.get("id"), "error": "Missing clip/package metadata"})
                continue
            source_video = project_root / clip_path
            package_file = project_root / package_path
            if not source_video.exists() or not package_file.exists():
                errors.append({"platform": platform, "clip_id": clip_id, "error": "Missing source video or package file"})
                continue

            package = load_json(package_file)
            post_dir = platform_root / safe_name(str(clip_id))
            post_dir.mkdir(parents=True, exist_ok=True)
            video_copy = post_dir / f"{safe_name(str(clip_id))}{source_video.suffix}"
            shutil.copy2(source_video, video_copy)

            hashtags = hashtags_for(package)
            title = package.get("suggested_title") or package.get("hook") or str(clip_id)
            caption = package.get("caption", "")
            posting_notes = "\n".join([
                f"Platform: {platform_label}",
                preset.get("manual_upload_notes", "Upload manually. No posting integration is configured."),
                "",
                f"Aspect guidance: {preset.get('aspect_rules', '')}",
                f"Duration guidance: {preset.get('duration_guidance', '')}",
                f"Title guidance: {preset.get('title_length_guidance', '')}",
                f"Hashtag guidance: {preset.get('hashtag_guidance', '')}",
            ])

            write_text(post_dir / "caption.txt", caption)
            write_text(post_dir / "hashtags.txt", " ".join(hashtags))
            write_text(post_dir / "title.txt", title)
            write_text(post_dir / "posting_notes.txt", posting_notes)
            write_text(post_dir / "upload_checklist.txt", checklist_text(platform_label, preset))

            thumbnail_rel = None
            cached = media_cache.get(str(clip_id), {})
            thumbnail_path = cached.get("thumbnail_path") if isinstance(cached, dict) else None
            if thumbnail_path and (project_root / thumbnail_path).exists():
                thumbnail_target = post_dir / "thumbnail.jpg"
                shutil.copy2(project_root / thumbnail_path, thumbnail_target)
                thumbnail_rel = relative_path(thumbnail_target, project_root)

            manifest = {
                "version": 1,
                "id": f"{platform}_{clip_id}",
                "platform": platform,
                "platform_label": platform_label,
                "manual_upload_only": True,
                "direct_posting_apis": False,
                "queue_entry_id": entry.get("id"),
                "clip_id": clip_id,
                "source_clip_path": clip_path,
                "source_package_path": package_path,
                "video": relative_path(video_copy, project_root),
                "caption_txt": relative_path(post_dir / "caption.txt", project_root),
                "hashtags_txt": relative_path(post_dir / "hashtags.txt", project_root),
                "title_txt": relative_path(post_dir / "title.txt", project_root),
                "posting_notes_txt": relative_path(post_dir / "posting_notes.txt", project_root),
                "upload_checklist_txt": relative_path(post_dir / "upload_checklist.txt", project_root),
                "thumbnail_jpg": thumbnail_rel,
                "preset": preset,
                "score": entry.get("score", package.get("score", 0)),
                "exported_at": utc_now(),
                "local_only": True,
            }
            (post_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            exported.append(manifest)

    summary = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "count": len(exported),
        "output_dir": relative_path(export_root, project_root),
        "platforms": selected_platforms,
        "exports": exported,
        "errors": errors,
    }
    (export_root / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    history_path = project_root / "analytics" / "social_export_history.json"
    history = load_json(history_path, {"runs": []})
    runs = history.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    runs.append({
        "updated_at": summary["updated_at"],
        "count": summary["count"],
        "platforms": selected_platforms,
        "output_dir": summary["output_dir"],
        "errors": errors,
    })
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps({"version": 1, "local_only": True, "runs": runs[-50:]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
