from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path


def probe_duration(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return float(payload["format"]["duration"])


def _clip_plan(duration: float, min_count: int, max_count: int, target_length: float) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    count = min(max_count, max(min_count, int(math.floor(duration / max(target_length, 1.0)))))
    clip_length = min(target_length, max(1.0, duration))
    if count == 1:
        return [(0.0, clip_length)]
    max_start = max(0.0, duration - clip_length)
    return [((max_start * i) / (count - 1), clip_length) for i in range(count)]


def generate_clips(video_record: dict[str, Any], video_path: Path, config: AppConfig) -> list[dict[str, Any]]:
    duration = probe_duration(video_path)
    video_record["duration_seconds"] = round(duration, 3)
    clip_specs = _clip_plan(
        duration,
        config.clip_count_min,
        config.clip_count_max,
        config.clip_duration_seconds,
    )
    video_clip_dir = config.clips_dir / video_record["id"]
    video_clip_dir.mkdir(parents=True, exist_ok=True)

    clips: list[dict[str, Any]] = []
    for index, (start, length) in enumerate(clip_specs, start=1):
        clip_id = f"{video_record['id']}_clip_{index:02d}"
        output_path = video_clip_dir / f"{clip_id}.mp4"
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(video_path),
                "-t",
                f"{length:.3f}",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        clips.append(
            {
                "id": clip_id,
                "path": relative_path(output_path, config.root),
                "start_seconds": round(start, 3),
                "duration_seconds": round(length, 3),
                "status": "generated",
            }
        )
    return clips
