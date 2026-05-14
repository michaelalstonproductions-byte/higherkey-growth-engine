#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.events import append_event
from growth_engine.index import load_index, mark_missing_source, resolve_media_path, save_index, utc_now
from growth_engine.json_store import load_json_file


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def path_exists(value: str | None, root: Path) -> bool:
    if not value:
        return False
    path = Path(value)
    if path.is_absolute():
        return path.exists()
    return (root / path).exists()


def repair_index(root: Path, prune_stale_queue: bool = False) -> dict[str, Any]:
    config = load_config(root)
    index = load_index(config.index_path)
    queue_payload = load_json_file(config.queue_path, {"entries": []})
    missing_sources: list[dict[str, Any]] = []
    repaired_sources: list[dict[str, Any]] = []
    missing_clips: list[dict[str, Any]] = []
    missing_packages: list[dict[str, Any]] = []
    missing_captions: list[dict[str, Any]] = []

    videos = index.setdefault("videos", {})
    for video_id, record in videos.items():
        original = record.get("source_path")
        resolved, attempts = resolve_media_path(original, config.root, config.inbox_dir)
        if resolved:
            repaired = rel(resolved, config.root)
            if original != repaired and not Path(str(original or "")).is_absolute():
                record["source_path"] = repaired
                record["updated_at"] = utc_now()
                repaired_sources.append({"video_id": video_id, "from": original, "to": repaired})
            elif record.get("status") == "missing_source":
                record["status"] = "registered" if not record.get("clips") else "processed"
                record["updated_at"] = utc_now()
                repaired_sources.append({"video_id": video_id, "from": original, "to": record.get("source_path")})
        else:
            mark_missing_source(record, original, attempts, "Source media is missing. It was skipped during project repair.")
            missing_sources.append({"video_id": video_id, "source_path": original, "resolved_attempts": attempts})

        for clip in record.get("clips", []):
            if not path_exists(clip.get("path"), config.root):
                clip["status"] = "missing_clip"
                clip["updated_at"] = utc_now()
                missing_clips.append({"video_id": video_id, "clip_id": clip.get("id"), "path": clip.get("path")})
        for package in record.get("packages", []):
            if not path_exists(package.get("path"), config.root):
                missing_packages.append({"video_id": video_id, "package_id": package.get("id"), "path": package.get("path")})
        for caption in record.get("captions", []):
            if not path_exists(caption.get("path"), config.root):
                missing_captions.append({"video_id": video_id, "caption_id": caption.get("id"), "path": caption.get("path")})

    stale_queue_entries = []
    valid_video_ids = {
        video_id for video_id, record in videos.items()
        if record.get("status") != "missing_source"
    }
    valid_clip_paths = {
        clip.get("path")
        for record in videos.values()
        for clip in record.get("clips", [])
        if clip.get("path") and path_exists(clip.get("path"), config.root)
    }
    queue_entries = queue_payload.get("entries", [])
    kept_entries = []
    for entry in queue_entries:
        stale_reasons = []
        if entry.get("source_video_id") not in valid_video_ids:
            stale_reasons.append("missing_source")
        if entry.get("clip_path") not in valid_clip_paths:
            stale_reasons.append("missing_clip")
        if entry.get("package_path") and not path_exists(entry.get("package_path"), config.root):
            stale_reasons.append("missing_package")
        if entry.get("caption_path") and not path_exists(entry.get("caption_path"), config.root):
            stale_reasons.append("missing_caption")
        if stale_reasons:
            stale_queue_entries.append({"id": entry.get("id"), "clip_id": entry.get("clip_id"), "reasons": stale_reasons})
            if prune_stale_queue:
                continue
        kept_entries.append(entry)

    save_index(config.index_path, index)
    if prune_stale_queue and len(kept_entries) != len(queue_entries):
        config.queue_path.write_text(json.dumps({
            "updated_at": utc_now(),
            "count": len(kept_entries),
            "entries": kept_entries,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "ok": True,
        "updated_at": utc_now(),
        "project_root": str(config.root),
        "missing_sources": missing_sources,
        "missing_clips": missing_clips,
        "missing_packages": missing_packages,
        "missing_captions": missing_captions,
        "repaired_sources": repaired_sources,
        "stale_queue_entries": stale_queue_entries,
        "pruned_stale_queue": prune_stale_queue,
        "counts": {
            "missing_sources": len(missing_sources),
            "missing_clips": len(missing_clips),
            "missing_packages": len(missing_packages),
            "missing_captions": len(missing_captions),
            "repaired_sources": len(repaired_sources),
            "stale_queue_entries": len(stale_queue_entries),
        },
        "report_path": "analytics/project_repair_report.json",
    }
    report_path = config.analytics_dir / "project_repair_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_event(config, "repair.completed", severity="info", source="repair_project_media", summary={"counts": report["counts"]})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair stale HigherKey media references without deleting media.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--prune-stale-queue", action="store_true", help="Remove stale queue entries after writing a repair report.")
    args = parser.parse_args()
    report = repair_index(Path(args.root), prune_stale_queue=args.prune_stale_queue)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
