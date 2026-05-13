from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


PLATFORM_NOTES = {
    "instagram": [
        "Use the hook in the first line.",
        "Keep caption readable without relying on external links.",
        "Review for vertical framing before posting.",
    ],
    "tiktok": [
        "Lead with the strongest motion or audio moment.",
        "Keep copy conversational and short.",
        "Confirm subtitles locally before publishing.",
    ],
    "youtube_shorts": [
        "Use the suggested title as a short, searchable title draft.",
        "Make the CTA specific to the next viewer action.",
        "Check that the opening seconds carry the premise.",
    ],
}


CTA_TEMPLATES = [
    "Save this for the next time you need a clear reminder.",
    "Share this with someone building momentum right now.",
    "Watch it twice and look for the detail in the middle.",
    "Use this as a prompt for your next move.",
    "Send this to the person who needs the shorter version.",
]


def _caption_payload(caption_record: dict[str, Any], root: Path) -> dict[str, Any]:
    if not caption_record:
        return {}
    path = root / caption_record["path"]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _subtitle_payload(subtitle_record: dict[str, Any], root: Path) -> dict[str, Any]:
    if not subtitle_record:
        return {}
    path = root / subtitle_record["path"]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _suggested_title(hook: str, clip: dict[str, Any]) -> str:
    if hook:
        return hook[:70]
    return f"Clip {clip['id']}"


def build_caption_packages(
    video_record: dict[str, Any],
    clips: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    captions_dir: Path,
    root: Path,
) -> list[dict[str, Any]]:
    package_dir = captions_dir / "packages" / video_record["id"]
    package_dir.mkdir(parents=True, exist_ok=True)
    captions_by_clip = {caption["clip_id"]: caption for caption in captions}
    subtitles_by_clip = {subtitle["id"].replace("_subtitles", ""): subtitle for subtitle in subtitles}
    packages: list[dict[str, Any]] = []

    for index, clip in enumerate(clips):
        caption_record = captions_by_clip.get(clip["id"], {})
        subtitle_record = subtitles_by_clip.get(clip["id"], {})
        caption_payload = _caption_payload(caption_record, root)
        subtitle_payload = _subtitle_payload(subtitle_record, root)
        hook = caption_payload.get("hook", "")
        package_id = f"{clip['id']}_package"
        output_path = package_dir / f"{package_id}.json"
        payload = {
            "id": package_id,
            "clip_id": clip["id"],
            "source_video_id": video_record["id"],
            "source_path": video_record["source_path"],
            "clip_path": clip["path"],
            "caption_path": caption_record.get("path"),
            "subtitle_path": subtitle_record.get("path"),
            "hook": hook,
            "caption": caption_payload.get("caption", ""),
            "hashtags": caption_payload.get("hashtags", []),
            "subtitle_status": subtitle_payload.get("status", subtitle_record.get("status", "not_extracted")),
            "has_audio": subtitle_payload.get("audio", {}).get("has_audio", subtitle_record.get("has_audio", False)),
            "audio_stream_count": subtitle_payload.get("audio", {}).get("audio_stream_count", subtitle_record.get("audio_stream_count", 0)),
            "suggested_title": _suggested_title(hook, clip),
            "suggested_cta": CTA_TEMPLATES[index % len(CTA_TEMPLATES)],
            "platform_notes": PLATFORM_NOTES,
            "score": clip.get("score", 0),
            "score_details": clip.get("score_details", {}),
            "hook_moments": clip.get("hook_moments", []),
            "scene_labels": clip.get("scene_labels", []),
            "analysis": clip.get("analysis", {}),
            "created_at": utc_now(),
            "status": "draft",
            "local_only": True,
        }
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        packages.append(
            {
                "id": package_id,
                "path": relative_path(output_path, root),
                "clip_id": clip["id"],
                "status": "draft",
            }
        )
    return packages
