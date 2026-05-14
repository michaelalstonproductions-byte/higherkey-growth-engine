from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

from .analytics import load_json, save_json
from .index import utc_now


COLOR_SCHOOL_VERSION = 1
SAMPLE_WIDTH = 64
SAMPLE_HEIGHT = 64
SAMPLE_SECONDS = 6
FFMPEG_TIMEOUT_SECONDS = 20


def _load_config(project_root: Path) -> dict[str, Any]:
    defaults = {
        "dark_threshold": 64,
        "bright_threshold": 205,
        "low_contrast_threshold": 28,
        "high_contrast_threshold": 78,
        "low_saturation_threshold": 0.16,
        "high_saturation_threshold": 0.72,
        "target_score": 80,
        "limit": None,
        "ffmpeg_timeout_seconds": FFMPEG_TIMEOUT_SECONDS,
    }
    config_path = project_root / "config" / "color_school.json"
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


def _sample_rgb(clip_path: Path, timeout_seconds: int = FFMPEG_TIMEOUT_SECONDS) -> tuple[list[int], int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip_path),
            "-vf",
            f"fps=1,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:force_original_aspect_ratio=increase,crop={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}",
            "-frames:v",
            str(SAMPLE_SECONDS),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    raw = result.stdout or b""
    return list(raw), len(raw) // (SAMPLE_WIDTH * SAMPLE_HEIGHT * 3)


def _metrics(samples: list[int], frame_count: int) -> dict[str, Any]:
    if not samples:
        return {"brightness": 0, "contrast": 0, "saturation": 0, "stability": 0, "frame_count": 0}
    brightness_values: list[float] = []
    saturation_values: list[float] = []
    for index in range(0, len(samples), 3):
        red, green, blue = samples[index], samples[index + 1], samples[index + 2]
        brightness = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        max_channel = max(red, green, blue) / 255.0
        min_channel = min(red, green, blue) / 255.0
        saturation = 0.0 if max_channel <= 0 else (max_channel - min_channel) / max_channel
        brightness_values.append(brightness)
        saturation_values.append(saturation)
    mean_brightness = statistics.fmean(brightness_values)
    contrast = statistics.pstdev(brightness_values) if len(brightness_values) > 1 else 0.0
    saturation = statistics.fmean(saturation_values)
    frame_means: list[float] = []
    pixels_per_frame = SAMPLE_WIDTH * SAMPLE_HEIGHT * 3
    for offset in range(0, len(samples), pixels_per_frame):
        frame = samples[offset : offset + pixels_per_frame]
        if frame:
            frame_means.append(statistics.fmean(frame[::3] or [0]))
    stability_delta = statistics.pstdev(frame_means) if len(frame_means) > 1 else 0.0
    stability = max(0.0, 100.0 - (stability_delta * 2.0))
    return {
        "brightness": round(mean_brightness, 2),
        "contrast": round(contrast, 2),
        "saturation": round(saturation, 4),
        "stability": round(stability, 2),
        "frame_count": frame_count,
    }


def _score(metrics: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    findings: list[str] = []
    recommendations: list[str] = []
    score = 100
    brightness = float(metrics.get("brightness", 0))
    contrast = float(metrics.get("contrast", 0))
    saturation = float(metrics.get("saturation", 0))
    stability = float(metrics.get("stability", 0))

    if brightness < config["dark_threshold"]:
        score -= 24
        findings.append("Frame reads dark on mobile.")
        recommendations.append("Preview a brighter export grade or choose a more readable clip segment.")
    elif brightness > config["bright_threshold"]:
        score -= 18
        findings.append("Highlights may read too bright.")
        recommendations.append("Preview highlight recovery or a softer exposure treatment.")
    else:
        findings.append("Brightness is in a readable range.")

    if contrast < config["low_contrast_threshold"]:
        score -= 14
        findings.append("Low contrast reduces scroll-stop clarity.")
        recommendations.append("Preview a contrast lift before publishing.")
    elif contrast > config["high_contrast_threshold"]:
        score -= 8
        findings.append("High contrast may crush detail.")
        recommendations.append("Preview a softer contrast curve.")
    else:
        findings.append("Contrast supports mobile readability.")

    if saturation < config["low_saturation_threshold"]:
        score -= 10
        findings.append("Saturation is muted.")
        recommendations.append("Preview a modest saturation lift.")
    elif saturation > config["high_saturation_threshold"]:
        score -= 8
        findings.append("Saturation is aggressive.")
        recommendations.append("Preview a more natural saturation pass.")
    else:
        findings.append("Color intensity is balanced.")

    if stability < 72:
        score -= 10
        findings.append("Color stability changes across the sampled frames.")
        recommendations.append("Check for mixed lighting before final export.")

    if not recommendations:
        recommendations.append("Color is ready for review; no repair action required.")
    return max(0, min(100, int(round(score)))), findings, recommendations


def _marker_candidates(score: int, findings: list[str]) -> list[dict[str, Any]]:
    if score >= 80:
        return []
    return [
        {
            "timestamp": 0,
            "label": "Color readiness check",
            "reason": findings[0] if findings else "Color school recommends review.",
        }
    ]


def analyze_color_school(project_root: Path, limit: int | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    config = _load_config(root)
    effective_limit = limit if limit is not None else config.get("limit")
    entries = _clip_entries(root, effective_limit)
    clips: list[dict[str, Any]] = []
    plan_items: list[dict[str, Any]] = []

    for entry in entries:
        clip_id = entry.get("clip_id") or entry.get("id") or "unknown"
        clip_path_value = entry.get("clip_path")
        clip_path = root / str(clip_path_value or "")
        if not clip_path_value or not clip_path.exists():
            item = {
                "clip_id": clip_id,
                "clip_path": clip_path_value,
                "status": "missing",
                "score": 0,
                "findings": ["Clip file is missing."],
                "safe_recommendations": ["Repair project media before reviewing color readiness."],
                "marker_candidates": [],
                "social_readiness_notes": "Color readiness unavailable until the clip exists.",
            }
            clips.append(item)
            continue
        try:
            samples, frame_count = _sample_rgb(clip_path, int(config["ffmpeg_timeout_seconds"]))
            metrics = _metrics(samples, frame_count)
            score, findings, recommendations = _score(metrics, config)
            status = "ready" if score >= int(config["target_score"]) else "review"
            item = {
                "clip_id": clip_id,
                "clip_path": clip_path_value,
                "status": status,
                "score": score,
                "metrics": metrics,
                "findings": findings,
                "safe_recommendations": recommendations,
                "marker_candidates": _marker_candidates(score, findings),
                "social_readiness_notes": "Color Readiness supports social review." if status == "ready" else "Preview color adjustments before publishing.",
            }
            clips.append(item)
            if status != "ready":
                plan_items.append({
                    "clip_id": clip_id,
                    "clip_path": clip_path_value,
                    "preview_plan": recommendations,
                    "read_only": True,
                })
        except Exception as exc:  # noqa: BLE001
            clips.append({
                "clip_id": clip_id,
                "clip_path": clip_path_value,
                "status": "error",
                "score": 0,
                "findings": ["Color analysis failed."],
                "safe_recommendations": ["Open Diagnostics for technical details, then rerun Color School."],
                "marker_candidates": [],
                "social_readiness_notes": "Color Readiness needs attention.",
                "error": str(exc),
            })

    ready_count = sum(1 for item in clips if item.get("status") == "ready")
    report = {
        "version": COLOR_SCHOOL_VERSION,
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
        },
        "report_path": "analytics/color_school_report.json",
        "repair_plan_path": "analytics/color_repair_plan.json",
        "clips": clips,
    }
    repair_plan = {
        "version": COLOR_SCHOOL_VERSION,
        "updated_at": report["updated_at"],
        "local_only": True,
        "read_only": True,
        "safe_preview_only": True,
        "items": plan_items,
    }
    save_json(root / "analytics" / "color_school_report.json", report)
    save_json(root / "analytics" / "color_repair_plan.json", repair_plan)
    return report
