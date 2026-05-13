from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .captions import generate_captions
from .config import AppConfig, ensure_directories
from .content_intelligence import analyze_clip
from .index import load_index, register_video, save_index, utc_now
from .ingest import discover_videos
from .media import generate_clips
from .packages import build_caption_packages
from .review_queue import build_queue_entries, save_review_queue
from .subtitles import create_subtitle_placeholders


def add_content_intelligence(clips: list[dict[str, Any]], config: AppConfig) -> None:
    for clip in clips:
        clip_path = config.root / clip["path"]
        try:
            analysis = analyze_clip(clip_path)
            clip["analysis"] = {
                "method": analysis["method"],
                "visual": analysis["visual"],
                "audio": analysis["audio"],
                "ocr": analysis["ocr"],
                "speech": analysis["speech"],
                "scene_labels": analysis["scene_labels"],
                "hook_moments": analysis["hook_moments"],
            }
            clip["hook_moments"] = analysis["hook_moments"]
            clip["scene_labels"] = analysis["scene_labels"]
            clip["score"] = analysis["score"]
            clip["score_details"] = analysis["score_details"]
        except Exception as exc:  # noqa: BLE001 - local analysis should not discard generated clips.
            clip["analysis"] = {"method": "ffmpeg_local_frame_and_audio_sampling", "error": str(exc)}
            clip["hook_moments"] = []
            clip["scene_labels"] = []
            clip["score"] = 0
            clip["score_details"] = {"reasons": ["analysis failed"]}


def _subtitle_records_stale(subtitles: list[dict[str, Any]], clips: list[dict[str, Any]]) -> bool:
    if len(subtitles) != len(clips):
        return True
    valid_statuses = {"pending_local_transcription", "no_audio"}
    return any(
        subtitle.get("status") not in valid_statuses or "has_audio" not in subtitle
        for subtitle in subtitles
    )


def _clips_need_multimodal(clips: list[dict[str, Any]]) -> bool:
    return any(
        "hook_moments" not in clip
        or "scene_labels" not in clip
        or "ocr" not in clip.get("analysis", {})
        or "speech" not in clip.get("analysis", {})
        for clip in clips
    )


def backfill_caption_packages(index: dict[str, Any], config: AppConfig) -> None:
    for record in index.get("videos", {}).values():
        clips = record.get("clips", [])
        captions = record.get("captions", [])
        if not clips or not captions:
            continue
        clips_need_multimodal = _clips_need_multimodal(clips)
        if clips_need_multimodal:
            add_content_intelligence(clips, config)
        subtitles = record.get("subtitles") or []
        subtitles_stale = _subtitle_records_stale(subtitles, clips)
        package_links_complete = record.get("packages") and all(entry.get("package_path") for entry in record.get("queue_entries", []))
        if package_links_complete and not subtitles_stale and not clips_need_multimodal:
            continue
        try:
            if subtitles_stale:
                subtitles = create_subtitle_placeholders(clips, config.captions_dir, config.root)
            packages = build_caption_packages(record, clips, captions, subtitles, config.captions_dir, config.root)
            record["subtitles"] = subtitles
            record["packages"] = packages
            record["queue_entries"] = build_queue_entries(record)
            record["updated_at"] = utc_now()
        except Exception as exc:  # noqa: BLE001 - legacy backfill should not block current processing.
            record.setdefault("errors", []).append({"at": utc_now(), "message": f"package backfill failed: {exc}"})


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
            add_content_intelligence(clips, config)
            captions = generate_captions(record, clips, config.captions_dir, config.root)
            subtitles = create_subtitle_placeholders(clips, config.captions_dir, config.root)
            packages = build_caption_packages(record, clips, captions, subtitles, config.captions_dir, config.root)
            record["clips"] = clips
            record["captions"] = captions
            record["subtitles"] = subtitles
            record["packages"] = packages
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

    backfill_caption_packages(index, config)
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
