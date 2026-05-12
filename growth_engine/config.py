from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass(frozen=True)
class AppConfig:
    root: Path
    inbox_dir: Path
    clips_dir: Path
    captions_dir: Path
    queue_dir: Path
    analytics_dir: Path
    logs_dir: Path
    index_path: Path
    queue_path: Path
    clip_count_min: int = 3
    clip_count_max: int = 5
    clip_duration_seconds: float = 8.0


def load_config(root: Path | None = None) -> AppConfig:
    project_root = (root or Path.cwd()).resolve()
    analytics_dir = project_root / "analytics"
    queue_dir = project_root / "queue"
    return AppConfig(
        root=project_root,
        inbox_dir=project_root / "content_inbox",
        clips_dir=project_root / "clips",
        captions_dir=project_root / "captions",
        queue_dir=queue_dir,
        analytics_dir=analytics_dir,
        logs_dir=project_root / "logs",
        index_path=analytics_dir / "video_index.json",
        queue_path=queue_dir / "review_queue.json",
    )


def ensure_directories(config: AppConfig) -> None:
    for path in (
        config.inbox_dir,
        config.clips_dir,
        config.captions_dir,
        config.queue_dir,
        config.analytics_dir,
        config.logs_dir,
        config.root / "out",
        config.root / "ingest",
        config.root / "config",
        config.root / "scripts",
    ):
        path.mkdir(parents=True, exist_ok=True)
