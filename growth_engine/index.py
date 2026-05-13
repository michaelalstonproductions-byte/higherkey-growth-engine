from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .json_store import load_json_file


INDEX_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha1()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(str(stat.st_size).encode("utf-8"))
    digest.update(str(int(stat.st_mtime)).encode("utf-8"))
    return digest.hexdigest()[:16]


def load_index(path: Path) -> dict[str, Any]:
    return load_json_file(path, {"version": INDEX_VERSION, "videos": {}})


def save_index(path: Path, index: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def register_video(index: dict[str, Any], video_path: Path, root: Path) -> dict[str, Any]:
    stat = video_path.stat()
    video_id = file_fingerprint(video_path)
    existing = index.setdefault("videos", {}).get(video_id, {})
    record = {
        "id": video_id,
        "source_path": relative_path(video_path, root),
        "filename": video_path.name,
        "size_bytes": stat.st_size,
        "mtime": int(stat.st_mtime),
        "registered_at": existing.get("registered_at", utc_now()),
        "updated_at": utc_now(),
        "status": existing.get("status", "registered"),
        "duration_seconds": existing.get("duration_seconds"),
        "clips": existing.get("clips", []),
        "captions": existing.get("captions", []),
        "subtitles": existing.get("subtitles", []),
        "packages": existing.get("packages", []),
        "queue_entries": existing.get("queue_entries", []),
        "errors": existing.get("errors", []),
    }
    index["videos"][video_id] = record
    return record
