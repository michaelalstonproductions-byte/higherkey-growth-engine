from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def approved_ids(payload: dict[str, Any]) -> set[str]:
    approved: set[str] = set()
    for key in ("approved_entry_ids", "approved_clip_ids"):
        values = payload.get(key, [])
        if isinstance(values, list):
            approved.update(str(value) for value in values)
    for item in payload.get("approved", []):
        if isinstance(item, str):
            approved.add(item)
        elif isinstance(item, dict):
            for key in ("id", "entry_id", "queue_id", "clip_id"):
                if item.get(key):
                    approved.add(str(item[key]))
    return approved


def _safe_dir_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_")


def _entry_is_approved(entry: dict[str, Any], approved: set[str]) -> bool:
    return entry.get("id") in approved or entry.get("clip_id") in approved


def export_approved_posts(
    root: Path,
    queue_path: Path | None = None,
    approvals_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    project_root = root.resolve()
    queue_file = queue_path or project_root / "queue" / "review_queue.json"
    approvals_file = approvals_path or project_root / "queue" / "approved_reviews.json"
    export_root = output_dir or project_root / "out" / "approved_posts"

    queue = load_json(queue_file)
    approvals = load_json(approvals_file)
    approved = approved_ids(approvals)
    if not approved:
        return {
            "exported": 0,
            "errors": [{"error": f"No approved IDs found in {relative_path(approvals_file, project_root)}"}],
            "output_dir": str(export_root),
        }

    export_root.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for entry in queue.get("entries", []):
        if not _entry_is_approved(entry, approved):
            continue
        clip_id = entry.get("clip_id")
        package_path = entry.get("package_path")
        clip_path = entry.get("clip_path")
        if not clip_id or not package_path or not clip_path:
            errors.append({"entry_id": entry.get("id", "unknown"), "error": "Missing clip or package path"})
            continue

        source_video = project_root / clip_path
        package_file = project_root / package_path
        if not source_video.exists():
            errors.append({"entry_id": entry.get("id", "unknown"), "error": f"Missing clip file: {clip_path}"})
            continue
        if not package_file.exists():
            errors.append({"entry_id": entry.get("id", "unknown"), "error": f"Missing package file: {package_path}"})
            continue

        package = load_json(package_file)
        post_dir = export_root / _safe_dir_name(clip_id)
        post_dir.mkdir(parents=True, exist_ok=True)
        final_video = post_dir / f"{_safe_dir_name(clip_id)}{source_video.suffix}"
        shutil.copy2(source_video, final_video)

        hashtags = package.get("hashtags", [])
        if not isinstance(hashtags, list):
            hashtags = []

        write_text(post_dir / "caption.txt", package.get("caption", ""))
        write_text(post_dir / "hashtags.txt", " ".join(str(tag) for tag in hashtags))
        write_text(post_dir / "title.txt", package.get("suggested_title", ""))
        (post_dir / "platform_notes.json").write_text(
            json.dumps(package.get("platform_notes", {}), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        manifest = {
            "id": f"approved_{clip_id}",
            "queue_entry_id": entry.get("id"),
            "clip_id": clip_id,
            "source_clip_path": clip_path,
            "source_package_path": package_path,
            "final_video": relative_path(final_video, project_root),
            "caption_txt": relative_path(post_dir / "caption.txt", project_root),
            "hashtags_txt": relative_path(post_dir / "hashtags.txt", project_root),
            "title_txt": relative_path(post_dir / "title.txt", project_root),
            "platform_notes_json": relative_path(post_dir / "platform_notes.json", project_root),
            "score": entry.get("score", package.get("score", 0)),
            "subtitle_status": package.get("subtitle_status", entry.get("subtitle_status")),
            "has_audio": package.get("has_audio"),
            "exported_at": utc_now(),
            "local_only": True,
            "status": "exported",
        }
        (post_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        exported.append(manifest)

    export_manifest = {
        "updated_at": utc_now(),
        "count": len(exported),
        "output_dir": relative_path(export_root, project_root),
        "approved_source": relative_path(approvals_file, project_root),
        "posts": exported,
        "errors": errors,
    }
    (export_root / "manifest.json").write_text(json.dumps(export_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "exported": len(exported),
        "errors": errors,
        "output_dir": str(export_root),
        "manifest_path": str(export_root / "manifest.json"),
    }
