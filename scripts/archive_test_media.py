#!/usr/bin/env python3
"""Move obvious smoke/generated media artifacts into a local archive folder."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PATTERNS = (
    "smoke_sample",
    "smoke-test",
    "smoke_test",
    "smoketest",
    "testsrc",
    "colorbar",
    "color_bar",
    "color-bars",
    "smptebars",
    "fixture",
)

SCAN_DIRS = (
    "content_inbox",
    "clips",
    "captions",
    "out/media_cache",
    "out/test_media",
)

MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".m4v",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".txt",
    ".vtt",
    ".srt",
    ".json",
}


def is_test_artifact(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in MEDIA_SUFFIXES:
        return False
    if any(pattern in name for pattern in PATTERNS):
        return True
    return name.startswith("test_") or name.endswith("_test.mp4") or name.endswith("-test.mp4")


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def main() -> int:
    root = Path.cwd().resolve()
    archive_root = root / "out" / "archived_test_media"
    moved = []
    skipped = []

    for dirname in SCAN_DIRS:
        source_root = root / dirname
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if not path.is_file():
                continue
            if archive_root in path.parents:
                continue
            if not is_test_artifact(path):
                skipped.append({"path": str(path.relative_to(root)), "reason": "not_test_artifact"})
                continue
            relative = path.relative_to(root)
            destination = unique_destination(archive_root / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
            moved.append({
                "from": str(relative),
                "to": str(destination.relative_to(root)),
            })

    summary = {
        "ok": True,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "archive_root": str(archive_root.relative_to(root)),
        "moved_count": len(moved),
        "moved": moved,
        "skipped_count": len(skipped),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
