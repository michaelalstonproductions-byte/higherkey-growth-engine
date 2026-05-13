from __future__ import annotations

import json
import math
import struct
import subprocess
from pathlib import Path
from typing import Any

from .analytics import load_json, save_json
from .index import relative_path, utc_now
from .media import probe_duration


MEDIA_CACHE_VERSION = 1
STRIP_FRAME_COUNT = 10
ENERGY_BAR_COUNT = 48


def _run(args: list[str], capture_binary: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=not capture_binary,
    )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value).strip("_") or "clip"


def _source_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"size_bytes": stat.st_size, "mtime": int(stat.st_mtime)}


def _probe_audio(clip_path: Path) -> bool:
    try:
        result = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(clip_path),
            ]
        )
        payload = json.loads(result.stdout or "{}")
        return bool(payload.get("streams"))
    except Exception:
        return False


def _timestamp(duration: float, index: int, count: int) -> float:
    if duration <= 0:
        return 0.0
    if count <= 1:
        return min(duration * 0.2, max(duration - 0.05, 0.0))
    padding = min(0.25, duration / 10.0)
    usable = max(duration - (padding * 2.0), 0.05)
    return min(duration - 0.05, padding + ((usable * index) / (count - 1)))


def _generate_thumbnail(clip_path: Path, output_path: Path, timestamp: float, width: int = 180, height: int = 320) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(clip_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            "3",
            str(output_path),
        ]
    )


def _generate_strip(clip_path: Path, output_path: Path, duration: float, count: int = STRIP_FRAME_COUNT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps = max(count / max(duration, 0.5), 0.1)
    vf = f"fps={fps:.4f},scale=96:170:force_original_aspect_ratio=increase,crop=96:170,tile={count}x1"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(clip_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            "4",
            str(output_path),
        ]
    )


def _audio_energy_bars(clip_path: Path, duration: float, bar_count: int = ENERGY_BAR_COUNT) -> list[dict[str, Any]]:
    result = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        capture_binary=True,
    )
    raw: bytes = result.stdout
    if not raw:
        return []
    samples = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) - (len(raw) % 2)])
    if not samples:
        return []
    bucket_size = max(1, math.ceil(len(samples) / bar_count))
    rms_values: list[float] = []
    for start in range(0, len(samples), bucket_size):
        bucket = samples[start : start + bucket_size]
        if not bucket:
            continue
        rms = math.sqrt(sum(sample * sample for sample in bucket) / len(bucket))
        rms_values.append(rms)
    peak = max(rms_values) if rms_values else 1.0
    if peak <= 0:
        peak = 1.0
    bars = []
    seconds_per_bar = duration / max(len(rms_values), 1)
    for index, value in enumerate(rms_values[:bar_count]):
        bars.append(
            {
                "index": index,
                "start": round(index * seconds_per_bar, 3),
                "end": round((index + 1) * seconds_per_bar, 3),
                "value": round(min(value / peak, 1.0), 4),
            }
        )
    return bars


def _hook_overlays(entry: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    overlays = []
    for moment in entry.get("hook_moments", []):
        timestamp = float(moment.get("timestamp", 0.0) or 0.0)
        overlays.append(
            {
                "timestamp": round(timestamp, 3),
                "position": round(timestamp / max(duration, 0.001), 4),
                "score": int(moment.get("score", entry.get("score", 0)) or 0),
                "reasons": moment.get("reasons", []),
            }
        )
    return overlays


def _existing_valid(existing: dict[str, Any], source: dict[str, Any], root: Path) -> bool:
    if existing.get("source_signature") != source:
        return False
    required = [existing.get("thumbnail_path"), existing.get("timeline_strip_path")]
    required.extend(frame.get("path") for frame in existing.get("strip_thumbnails", []))
    return all(path_value and (root / path_value).exists() for path_value in required)


def _build_clip_cache(root: Path, entry: dict[str, Any], existing: dict[str, Any] | None, force: bool) -> dict[str, Any]:
    clip_id = entry.get("clip_id") or entry.get("id")
    clip_path_value = entry.get("clip_path")
    if not clip_id or not clip_path_value:
        return {"clip_id": clip_id or "unknown", "status": "error", "errors": ["missing clip_id or clip_path"]}
    clip_path = root / clip_path_value
    if not clip_path.exists():
        return {"clip_id": clip_id, "status": "missing", "errors": [f"missing clip file: {clip_path_value}"]}

    signature = _source_signature(clip_path)
    if existing and not force and _existing_valid(existing, signature, root):
        reused = dict(existing)
        reused["status"] = "cached"
        reused["cache_hit"] = True
        return reused

    cache_dir = root / "out" / "media_cache" / _safe_name(str(clip_id))
    duration = probe_duration(clip_path)
    thumbnail_path = cache_dir / "thumbnail.jpg"
    timeline_strip_path = cache_dir / "timeline_strip.jpg"
    strip_frames: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        _generate_thumbnail(clip_path, thumbnail_path, _timestamp(duration, 1, 5), 180, 320)
    except Exception as exc:  # noqa: BLE001 - cache errors are per-clip and persisted.
        errors.append(f"thumbnail failed: {exc}")

    try:
        _generate_strip(clip_path, timeline_strip_path, duration, STRIP_FRAME_COUNT)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"timeline strip failed: {exc}")

    for index in range(STRIP_FRAME_COUNT):
        frame_path = cache_dir / f"strip_{index + 1:02d}.jpg"
        timestamp = _timestamp(duration, index, STRIP_FRAME_COUNT)
        try:
            _generate_thumbnail(clip_path, frame_path, timestamp, 120, 213)
            strip_frames.append(
                {
                    "index": index,
                    "timestamp": round(timestamp, 3),
                    "position": round(timestamp / max(duration, 0.001), 4),
                    "path": relative_path(frame_path, root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"strip frame {index + 1} failed: {exc}")

    has_audio = _probe_audio(clip_path)
    energy_bars: list[dict[str, Any]] = []
    if has_audio:
        try:
            energy_bars = _audio_energy_bars(clip_path, duration, ENERGY_BAR_COUNT)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"audio energy failed: {exc}")

    return {
        "clip_id": clip_id,
        "queue_entry_id": entry.get("id"),
        "source_path": entry.get("source_path"),
        "clip_path": clip_path_value,
        "status": "error" if errors else "cached",
        "cache_hit": False,
        "cached_at": utc_now(),
        "source_signature": signature,
        "duration_seconds": round(duration, 3),
        "thumbnail_path": relative_path(thumbnail_path, root) if thumbnail_path.exists() else None,
        "timeline_strip_path": relative_path(timeline_strip_path, root) if timeline_strip_path.exists() else None,
        "strip_thumbnails": strip_frames,
        "waveform": {
            "has_audio": has_audio,
            "bar_count": len(energy_bars),
            "bars": energy_bars,
        },
        "hook_overlays": _hook_overlays(entry, duration),
        "score": entry.get("score", 0),
        "errors": errors,
    }


def build_media_cache(root: Path, force: bool = False, limit: int | None = None) -> dict[str, Any]:
    project_root = root.resolve()
    queue = load_json(project_root / "queue" / "review_queue.json", {"entries": []})
    manifest_path = project_root / "analytics" / "media_cache.json"
    existing_manifest = load_json(manifest_path, {"clips": {}})
    existing_clips = existing_manifest.get("clips", {})
    entries = queue.get("entries", [])
    if limit is not None:
        entries = entries[: max(limit, 0)]

    clips: dict[str, Any] = {}
    for entry in entries:
        clip_id = entry.get("clip_id") or entry.get("id") or "unknown"
        clips[str(clip_id)] = _build_clip_cache(project_root, entry, existing_clips.get(str(clip_id)), force)

    status_counts: dict[str, int] = {}
    for item in clips.values():
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    payload = {
        "version": MEDIA_CACHE_VERSION,
        "updated_at": utc_now(),
        "local_only": True,
        "generator": "ffmpeg_thumbnail_strip_pcm_energy_v1",
        "asset_root": relative_path(project_root / "out" / "media_cache", project_root),
        "source_queue": relative_path(project_root / "queue" / "review_queue.json", project_root),
        "count": len(clips),
        "status_counts": status_counts,
        "clips": clips,
    }
    save_json(manifest_path, payload)
    return {
        "cached": status_counts.get("cached", 0),
        "errors": status_counts.get("error", 0),
        "missing": status_counts.get("missing", 0),
        "count": len(clips),
        "manifest_path": str(manifest_path),
        "asset_root": str(project_root / "out" / "media_cache"),
    }
