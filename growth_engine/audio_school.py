from __future__ import annotations

import json
import math
import statistics
import struct
import subprocess
from pathlib import Path
from typing import Any

from .analytics import load_json, save_json
from .index import utc_now


AUDIO_SCHOOL_VERSION = 1
SAMPLE_RATE = 8000
SAMPLE_SECONDS = 20
FFMPEG_TIMEOUT_SECONDS = 25
FFPROBE_TIMEOUT_SECONDS = 15


def _load_config(project_root: Path) -> dict[str, Any]:
    defaults = {
        "target_score": 80,
        "low_energy_threshold": 0.018,
        "silence_threshold": 0.006,
        "silence_risk_ratio": 0.58,
        "peak_clip_threshold": 0.96,
        "sample_seconds": SAMPLE_SECONDS,
        "preview_points": 80,
        "limit": None,
        "ffmpeg_timeout_seconds": FFMPEG_TIMEOUT_SECONDS,
        "ffprobe_timeout_seconds": FFPROBE_TIMEOUT_SECONDS,
        "write_previews": True,
    }
    config_path = project_root / "config" / "audio_school.json"
    if not config_path.exists():
        return defaults
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return {**defaults, **payload}
    except Exception:
        return defaults


def _clip_entries(project_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    queue = load_json(project_root / "queue" / "review_queue.json", {"entries": []})
    entries = queue.get("entries", [])
    if limit is not None:
        return entries[: max(limit, 0)]
    return entries


def _audio_streams(clip_path: Path, timeout_seconds: int = FFPROBE_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index,codec_name,channels,sample_rate",
            "-of",
            "json",
            str(clip_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ffprobe audio stream check failed").strip())
    payload = json.loads(result.stdout or "{}")
    return payload.get("streams", [])


def _sample_audio(clip_path: Path, sample_seconds: int, timeout_seconds: int = FFMPEG_TIMEOUT_SECONDS) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip_path),
            "-t",
            str(sample_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    return result.stdout or b""


def _pcm_samples(raw: bytes) -> list[int]:
    count = len(raw) // 2
    if count <= 0:
        return []
    return list(struct.unpack(f"<{count}h", raw[: count * 2]))


def _metrics(samples: list[int], config: dict[str, Any]) -> dict[str, Any]:
    if not samples:
        return {"energy": 0, "peak": 0, "silence_ratio": 1, "dynamic_range": 0, "sample_count": 0}
    normalized = [sample / 32768.0 for sample in samples]
    energy = math.sqrt(statistics.fmean(value * value for value in normalized))
    peak = max(abs(value) for value in normalized)
    silence_threshold = float(config["silence_threshold"])
    silence_ratio = sum(1 for value in normalized if abs(value) < silence_threshold) / len(normalized)
    block_size = max(1, SAMPLE_RATE // 2)
    block_energy: list[float] = []
    for offset in range(0, len(normalized), block_size):
        block = normalized[offset : offset + block_size]
        if block:
            block_energy.append(math.sqrt(statistics.fmean(value * value for value in block)))
    dynamic_range = statistics.pstdev(block_energy) if len(block_energy) > 1 else 0.0
    return {
        "energy": round(energy, 5),
        "peak": round(peak, 5),
        "silence_ratio": round(silence_ratio, 4),
        "dynamic_range": round(dynamic_range, 5),
        "sample_count": len(samples),
    }


def _preview_points(samples: list[int], config: dict[str, Any]) -> list[float]:
    if not samples:
        return []
    point_count = int(config["preview_points"])
    chunk = max(1, len(samples) // point_count)
    points: list[float] = []
    for offset in range(0, len(samples), chunk):
        block = samples[offset : offset + chunk]
        if block:
            rms = math.sqrt(statistics.fmean((sample / 32768.0) ** 2 for sample in block))
            points.append(round(min(1.0, rms * 8.0), 4))
        if len(points) >= point_count:
            break
    return points


def _classification(metrics: dict[str, Any]) -> str:
    energy = float(metrics.get("energy", 0))
    dynamic_range = float(metrics.get("dynamic_range", 0))
    silence_ratio = float(metrics.get("silence_ratio", 1))
    if silence_ratio > 0.72:
        return "silence risk"
    if dynamic_range > 0.035 and energy > 0.04:
        return "music or high-energy ambience"
    if dynamic_range > 0.018:
        return "dialogue or mixed audio"
    return "ambience or low-energy bed"


def _score(has_audio: bool, metrics: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    if not has_audio:
        return (
            35,
            ["No audio stream was detected."],
            ["Review whether captions or a silent-friendly edit are needed before publishing."],
        )
    score = 100
    findings: list[str] = []
    recommendations: list[str] = []
    energy = float(metrics.get("energy", 0))
    peak = float(metrics.get("peak", 0))
    silence_ratio = float(metrics.get("silence_ratio", 1))

    if energy < float(config["low_energy_threshold"]):
        score -= 22
        findings.append("Audio energy is low for mobile playback.")
        recommendations.append("Preview a louder export mix or choose a segment with clearer audio presence.")
    else:
        findings.append("Audio energy is present for mobile playback.")

    if silence_ratio > float(config["silence_risk_ratio"]):
        score -= 18
        findings.append("Long quiet sections may reduce retention.")
        recommendations.append("Preview tighter pacing or captions for quiet sections.")
    else:
        findings.append("Silence risk is controlled.")

    if peak > float(config["peak_clip_threshold"]):
        score -= 16
        findings.append("Peak levels are close to clipping.")
        recommendations.append("Preview a softer master level before publishing.")
    else:
        findings.append("Peak levels are within a safe preview range.")

    classification = _classification(metrics)
    findings.append(f"Detected profile: {classification}.")

    if not recommendations:
        recommendations.append("Audio is ready for review; no repair action required.")
    return max(0, min(100, int(round(score)))), findings, recommendations


def _marker_candidates(score: int, findings: list[str]) -> list[dict[str, Any]]:
    if score >= 80:
        return []
    return [
        {
            "timestamp": 0,
            "label": "Audio readiness check",
            "reason": findings[0] if findings else "Audio School recommends review.",
        }
    ]


def analyze_audio_school(project_root: Path, limit: int | None = None, write_previews: bool | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    config = _load_config(root)
    effective_limit = limit if limit is not None else config.get("limit")
    entries = _clip_entries(root, effective_limit)
    should_write_previews = bool(config.get("write_previews", True) if write_previews is None else write_previews)
    preview_dir = root / "out" / "audio_school" / "previews"
    if should_write_previews:
        preview_dir.mkdir(parents=True, exist_ok=True)
    clips: list[dict[str, Any]] = []
    plan_items: list[dict[str, Any]] = []

    for entry in entries:
        clip_id = entry.get("clip_id") or entry.get("id") or "unknown"
        clip_path_value = entry.get("clip_path")
        clip_path = root / str(clip_path_value or "")
        if not clip_path_value or not clip_path.exists():
            clips.append(
                {
                    "clip_id": clip_id,
                    "clip_path": clip_path_value,
                    "has_audio": False,
                    "status": "missing",
                    "score": 0,
                    "findings": ["Clip file is missing."],
                    "safe_recommendations": ["Repair project media before reviewing audio readiness."],
                    "marker_candidates": [],
                    "social_readiness_notes": "Audio Readiness unavailable until the clip exists.",
                }
            )
            continue
        try:
            streams = _audio_streams(clip_path, int(config["ffprobe_timeout_seconds"]))
            has_audio = bool(streams)
            metrics = {"energy": 0, "peak": 0, "silence_ratio": 1, "dynamic_range": 0, "sample_count": 0}
            preview_path = None
            if has_audio:
                raw = _sample_audio(clip_path, int(config["sample_seconds"]), int(config["ffmpeg_timeout_seconds"]))
                samples = _pcm_samples(raw)
                metrics = _metrics(samples, config)
                if should_write_previews:
                    preview = {
                        "clip_id": clip_id,
                        "clip_path": clip_path_value,
                        "updated_at": utc_now(),
                        "points": _preview_points(samples, config),
                        "read_only": True,
                    }
                    preview_name = f"{str(clip_id).replace('/', '_')}.json"
                    preview_output = preview_dir / preview_name
                    save_json(preview_output, preview)
                    preview_path = f"out/audio_school/previews/{preview_name}"
            score, findings, recommendations = _score(has_audio, metrics, config)
            status = "ready" if score >= int(config["target_score"]) else "review"
            item = {
                "clip_id": clip_id,
                "clip_path": clip_path_value,
                "has_audio": has_audio,
                "status": status,
                "score": score,
                "metrics": metrics,
                "audio_streams": streams,
                "preview_path": preview_path,
                "findings": findings,
                "safe_recommendations": recommendations,
                "marker_candidates": _marker_candidates(score, findings),
                "social_readiness_notes": "Audio Readiness supports social review." if status == "ready" else "Preview audio adjustments before publishing.",
            }
            clips.append(item)
            if status != "ready":
                plan_items.append(
                    {
                        "clip_id": clip_id,
                        "clip_path": clip_path_value,
                        "preview_plan": recommendations,
                        "read_only": True,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            clips.append(
                {
                    "clip_id": clip_id,
                    "clip_path": clip_path_value,
                    "has_audio": False,
                    "status": "error",
                    "score": 0,
                    "findings": ["Audio analysis failed."],
                    "safe_recommendations": ["Open Diagnostics for technical details, then rerun Audio School."],
                    "marker_candidates": [],
                    "social_readiness_notes": "Audio Readiness needs attention.",
                    "error": str(exc),
                }
            )

    ready_count = sum(1 for item in clips if item.get("status") == "ready")
    report = {
        "version": AUDIO_SCHOOL_VERSION,
        "updated_at": utc_now(),
        "local_only": True,
        "read_only": True,
        "status": "pass" if ready_count == len(clips) else ("warn" if clips else "empty"),
        "summary": {
            "clips": len(clips),
            "ready": ready_count,
            "review": sum(1 for item in clips if item.get("status") == "review"),
            "missing": sum(1 for item in clips if item.get("status") == "missing"),
            "errors": sum(1 for item in clips if item.get("status") == "error"),
            "with_audio": sum(1 for item in clips if item.get("has_audio")),
        },
        "report_path": "analytics/audio_school_report.json",
        "repair_plan_path": "analytics/audio_repair_plan.json",
        "preview_dir": "out/audio_school/previews",
        "previews_written": should_write_previews,
        "clips": clips,
    }
    repair_plan = {
        "version": AUDIO_SCHOOL_VERSION,
        "updated_at": report["updated_at"],
        "local_only": True,
        "read_only": True,
        "safe_preview_only": True,
        "items": plan_items,
    }
    save_json(root / "analytics" / "audio_school_report.json", report)
    save_json(root / "analytics" / "audio_repair_plan.json", repair_plan)
    return report
