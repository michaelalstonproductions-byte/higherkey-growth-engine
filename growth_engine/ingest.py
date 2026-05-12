from __future__ import annotations

from pathlib import Path

from .config import VIDEO_EXTENSIONS


def discover_videos(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.exists():
        return []
    return sorted(
        path
        for path in inbox_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
