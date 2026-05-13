from __future__ import annotations

import math
import statistics
import subprocess
from pathlib import Path
from typing import Any


FRAME_WIDTH = 96
FRAME_HEIGHT = 170
FRAME_BYTES = FRAME_WIDTH * FRAME_HEIGHT * 3


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def _sample_frames(clip_path: Path, sample_fps: float = 2.0) -> list[bytes]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip_path),
            "-vf",
            f"fps={sample_fps},scale={FRAME_WIDTH}:{FRAME_HEIGHT}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    raw = result.stdout
    return [raw[index : index + FRAME_BYTES] for index in range(0, len(raw), FRAME_BYTES) if len(raw[index : index + FRAME_BYTES]) == FRAME_BYTES]


def _luma_values(frame: bytes) -> list[float]:
    values: list[float] = []
    for index in range(0, len(frame), 3):
        red = frame[index]
        green = frame[index + 1]
        blue = frame[index + 2]
        values.append((0.2126 * red) + (0.7152 * green) + (0.0722 * blue))
    return values


def _visual_metrics(clip_path: Path) -> dict[str, Any]:
    frames = _sample_frames(clip_path)
    if not frames:
        return {
            "sampled_frames": 0,
            "scene_changes": 0,
            "motion_intensity": 0.0,
            "brightness_mean": 0.0,
            "brightness_change": 0.0,
            "contrast_mean": 0.0,
            "contrast_change": 0.0,
        }

    brightness_values: list[float] = []
    contrast_values: list[float] = []
    frame_lumas: list[list[float]] = []
    for frame in frames:
        lumas = _luma_values(frame)
        frame_lumas.append(lumas)
        brightness_values.append(statistics.fmean(lumas))
        contrast_values.append(statistics.pstdev(lumas))

    diffs: list[float] = []
    for previous, current in zip(frame_lumas, frame_lumas[1:]):
        diffs.append(statistics.fmean(abs(a - b) for a, b in zip(previous, current)))

    scene_threshold = 32.0
    scene_changes = sum(1 for diff in diffs if diff >= scene_threshold)
    motion_intensity = statistics.fmean(diffs) if diffs else 0.0

    return {
        "sampled_frames": len(frames),
        "scene_changes": scene_changes,
        "motion_intensity": round(motion_intensity, 3),
        "brightness_mean": round(statistics.fmean(brightness_values), 3),
        "brightness_change": round(max(brightness_values) - min(brightness_values), 3),
        "contrast_mean": round(statistics.fmean(contrast_values), 3),
        "contrast_change": round(max(contrast_values) - min(contrast_values), 3),
    }


def _audio_metrics(clip_path: Path) -> dict[str, Any]:
    try:
        result = _run_ffmpeg(
            [
                "ffmpeg",
                "-v",
                "info",
                "-i",
                str(clip_path),
                "-af",
                "astats=metadata=1:reset=0.5",
                "-f",
                "null",
                "-",
            ]
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if (
            "Stream specifier" in stderr
            or "matches no streams" in stderr
            or "Cannot find a matching stream" in stderr
            or "does not contain any stream" in stderr
        ):
            return {"rms_level_db": None, "peak_level_db": None, "audio_energy_peaks": 0}
        raise

    rms_levels: list[float] = []
    peak_levels: list[float] = []
    for line in result.stderr.splitlines():
        if "RMS level dB:" in line:
            value = line.rsplit(":", 1)[-1].strip()
            if value != "-inf":
                rms_levels.append(float(value))
        elif "Peak level dB:" in line:
            value = line.rsplit(":", 1)[-1].strip()
            if value != "-inf":
                peak_levels.append(float(value))

    if not rms_levels:
        return {"rms_level_db": None, "peak_level_db": None, "audio_energy_peaks": 0}

    peak_threshold = statistics.fmean(rms_levels) + max(1.5, statistics.pstdev(rms_levels))
    return {
        "rms_level_db": round(statistics.fmean(rms_levels), 3),
        "peak_level_db": round(max(peak_levels), 3) if peak_levels else None,
        "audio_energy_peaks": sum(1 for level in rms_levels if level >= peak_threshold),
    }


def score_hook_potential(analysis: dict[str, Any]) -> dict[str, Any]:
    visual = analysis.get("visual", {})
    audio = analysis.get("audio", {})
    scene_score = _clamp(float(visual.get("scene_changes", 0)) * 18.0, 0.0, 30.0)
    motion_score = _clamp(float(visual.get("motion_intensity", 0.0)) / 45.0 * 30.0, 0.0, 30.0)
    brightness_score = _clamp(float(visual.get("brightness_change", 0.0)) / 80.0 * 15.0, 0.0, 15.0)
    contrast_score = _clamp(float(visual.get("contrast_change", 0.0)) / 45.0 * 10.0, 0.0, 10.0)
    audio_score = _clamp(float(audio.get("audio_energy_peaks", 0)) * 5.0, 0.0, 15.0)
    total = scene_score + motion_score + brightness_score + contrast_score + audio_score

    reasons: list[str] = []
    if scene_score >= 12:
        reasons.append("visual cuts")
    if motion_score >= 12:
        reasons.append("motion")
    if audio_score >= 5:
        reasons.append("audio peaks")
    if brightness_score + contrast_score >= 8:
        reasons.append("light/contrast shift")
    if not reasons:
        reasons.append("steady clip")

    return {
        "score": int(round(_clamp(total, 0.0, 100.0))),
        "score_details": {
            "scene_score": round(scene_score, 2),
            "motion_score": round(motion_score, 2),
            "brightness_score": round(brightness_score, 2),
            "contrast_score": round(contrast_score, 2),
            "audio_score": round(audio_score, 2),
            "reasons": reasons,
        },
    }


def analyze_clip(clip_path: Path) -> dict[str, Any]:
    analysis = {
        "visual": _visual_metrics(clip_path),
        "audio": _audio_metrics(clip_path),
        "method": "ffmpeg_local_frame_and_audio_sampling",
    }
    analysis.update(score_hook_potential(analysis))
    if math.isnan(float(analysis["score"])):
        analysis["score"] = 0
    return analysis
