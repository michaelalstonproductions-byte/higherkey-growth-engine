from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


HOOK_TEMPLATES = [
    "The moment this shifted everything",
    "Watch what happens when the pressure hits",
    "This is the part most people miss",
    "A quick lesson from the middle of the action",
    "The detail that changes the whole story",
]


def generate_captions(video_record: dict[str, Any], clips: list[dict[str, Any]], captions_dir: Path, root: Path) -> list[dict[str, Any]]:
    video_caption_dir = captions_dir / video_record["id"]
    video_caption_dir.mkdir(parents=True, exist_ok=True)
    captions: list[dict[str, Any]] = []

    for index, clip in enumerate(clips):
        caption_id = f"{clip['id']}_caption"
        hook = HOOK_TEMPLATES[index % len(HOOK_TEMPLATES)]
        payload = {
            "id": caption_id,
            "clip_id": clip["id"],
            "source_video_id": video_record["id"],
            "hook": hook,
            "caption": f"{hook}. Placeholder caption for review before publishing.",
            "hashtags": ["#HigherKey", "#Growth", "#BehindTheScenes"],
            "created_at": utc_now(),
            "status": "draft",
        }
        caption_path = video_caption_dir / f"{caption_id}.json"
        caption_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        captions.append(
            {
                "id": caption_id,
                "path": relative_path(caption_path, root),
                "clip_id": clip["id"],
                "status": "draft",
            }
        )
    return captions
