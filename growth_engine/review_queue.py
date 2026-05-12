from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .index import utc_now


def build_queue_entries(video_record: dict[str, Any]) -> list[dict[str, Any]]:
    captions_by_clip = {caption["clip_id"]: caption for caption in video_record.get("captions", [])}
    entries: list[dict[str, Any]] = []
    for clip in video_record.get("clips", []):
        caption = captions_by_clip.get(clip["id"])
        entries.append(
            {
                "id": f"queue_{clip['id']}",
                "source_video_id": video_record["id"],
                "source_path": video_record["source_path"],
                "clip_id": clip["id"],
                "clip_path": clip["path"],
                "caption_id": caption["id"] if caption else None,
                "caption_path": caption["path"] if caption else None,
                "status": "needs_review",
                "review_notes": "",
                "created_at": utc_now(),
            }
        )
    return entries


def save_review_queue(path: Path, index: dict[str, Any]) -> list[dict[str, Any]]:
    all_entries: list[dict[str, Any]] = []
    for video in sorted(index.get("videos", {}).values(), key=lambda item: item["registered_at"]):
        all_entries.extend(video.get("queue_entries", []))
    payload = {
        "updated_at": utc_now(),
        "count": len(all_entries),
        "entries": all_entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return all_entries
