from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .captions import generate_captions
from .config import AppConfig, ensure_directories
from .index import load_index, register_video, save_index, utc_now
from .ingest import discover_videos
from .media import generate_clips
from .review_queue import build_queue_entries, save_review_queue


def process_once(config: AppConfig) -> dict[str, Any]:
    ensure_directories(config)
    index = load_index(config.index_path)
    videos = discover_videos(config.inbox_dir)
    processed = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    for video_path in videos:
        record = register_video(index, video_path, config.root)
        if record.get("status") == "processed" and record.get("clips"):
            skipped += 1
            continue
        try:
            record["status"] = "processing"
            record["updated_at"] = utc_now()
            clips = generate_clips(record, video_path, config)
            captions = generate_captions(record, clips, config.captions_dir, config.root)
            record["clips"] = clips
            record["captions"] = captions
            record["queue_entries"] = build_queue_entries(record)
            record["status"] = "processed"
            record["updated_at"] = utc_now()
            processed += 1
        except Exception as exc:  # noqa: BLE001 - prototype should preserve failure detail locally.
            message = str(exc)
            record["status"] = "error"
            record["updated_at"] = utc_now()
            record.setdefault("errors", []).append({"at": utc_now(), "message": message})
            errors.append({"video": record["source_path"], "error": message})

    queue_entries = save_review_queue(config.queue_path, index)
    save_index(config.index_path, index)
    return {
        "discovered": len(videos),
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "queue_entries": len(queue_entries),
        "index_path": str(config.index_path),
        "queue_path": str(config.queue_path),
    }


def watch(config: AppConfig, interval_seconds: float = 5.0) -> None:
    while True:
        process_once(config)
        time.sleep(interval_seconds)
