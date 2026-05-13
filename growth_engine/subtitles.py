from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


def create_subtitle_placeholder(clip: dict[str, Any], captions_dir: Path, root: Path) -> dict[str, Any]:
    subtitle_dir = captions_dir / "subtitles" / clip["id"].rsplit("_clip_", 1)[0]
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    output_path = subtitle_dir / f"{clip['id']}_subtitles.json"
    payload = {
        "id": f"{clip['id']}_subtitles",
        "clip_id": clip["id"],
        "status": "not_extracted",
        "method": "placeholder",
        "segments": [],
        "notes": "Reserved for future local subtitle extraction. No cloud transcription is used.",
        "created_at": utc_now(),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "id": payload["id"],
        "path": relative_path(output_path, root),
        "status": payload["status"],
        "method": payload["method"],
    }


def create_subtitle_placeholders(clips: list[dict[str, Any]], captions_dir: Path, root: Path) -> list[dict[str, Any]]:
    return [create_subtitle_placeholder(clip, captions_dir, root) for clip in clips]
