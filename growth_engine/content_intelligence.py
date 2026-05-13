from __future__ import annotations

import math
import statistics
import subprocess
from pathlib import Path
from typing import Any


FRAME_WIDTH = 96
FRAME_HEIGHT = 170
FRAME_BYTES = FRAME_WIDTH * FRAME_HEIGHT * 3
SAMPLE_FPS = 2.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def _sample_frames(clip_path: Path, sample_fps: float = SAMPLE_FPS) -> list[bytes]:
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
    frames = _sample_frames(clip_path, SAMPLE_FPS)
    if not frames:
        return {
            "sampled_frames": 0,
            "frame_sampling": {
                "status": "failed",
                "sample_fps": SAMPLE_FPS,
                "width": FRAME_WIDTH,
                "height": FRAME_HEIGHT,
            },
            "scene_changes": 0,
            "scene_change_timestamps": [],
            "motion_spike_timestamps": [],
            "motion_samples": [],
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
    motion_threshold = max(12.0, (statistics.fmean(diffs) if diffs else 0.0) + (statistics.pstdev(diffs) if len(diffs) > 1 else 0.0))
    scene_changes = sum(1 for diff in diffs if diff >= scene_threshold)
    motion_intensity = statistics.fmean(diffs) if diffs else 0.0
    motion_samples = [
        {"timestamp": round((index + 1) / SAMPLE_FPS, 3), "delta": round(diff, 3)}
        for index, diff in enumerate(diffs)
    ]

    return {
        "sampled_frames": len(frames),
        "frame_sampling": {
            "status": "sampled",
            "sample_fps": SAMPLE_FPS,
            "width": FRAME_WIDTH,
            "height": FRAME_HEIGHT,
            "sampled_frames": len(frames),
            "purpose": "future_local_vision_analysis",
        },
        "scene_changes": scene_changes,
        "scene_change_timestamps": [
            sample["timestamp"] for sample in motion_samples if sample["delta"] >= scene_threshold
        ],
        "motion_spike_timestamps": [
            sample["timestamp"] for sample in motion_samples if sample["delta"] >= motion_threshold
        ],
        "motion_samples": motion_samples,
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
            return {"rms_level_db": None, "peak_level_db": None, "audio_energy_peaks": 0, "audio_peak_timestamps": []}
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
        return {"rms_level_db": None, "peak_level_db": None, "audio_energy_peaks": 0, "audio_peak_timestamps": []}

    peak_threshold = statistics.fmean(rms_levels) + max(1.5, statistics.pstdev(rms_levels))
    peak_indexes = [index for index, level in enumerate(rms_levels) if level >= peak_threshold]
    return {
        "rms_level_db": round(statistics.fmean(rms_levels), 3),
        "peak_level_db": round(max(peak_levels), 3) if peak_levels else None,
        "audio_energy_peaks": len(peak_indexes),
        "audio_peak_timestamps": [round(index * 0.5, 3) for index in peak_indexes],
    }


def _ocr_placeholder(visual: dict[str, Any]) -> dict[str, Any]:
    return {
        "ocr_status": "not_configured",
        "engine": {
            "name": "local_ocr_placeholder",
            "configured": False,
            "required": False,
        },
        "detected_text": [],
        "detected_text_frequency": 0.0,
        "frame_sample_count": visual.get("sampled_frames", 0),
        "notes": "Reserved for future local OCR over sampled frames. No cloud OCR is used.",
    }


def _speech_placeholder(audio: dict[str, Any]) -> dict[str, Any]:
    has_audio_signal = audio.get("rms_level_db") is not None
    return {
        "transcription_status": "pending_local_transcription" if has_audio_signal else "no_audio_signal",
        "engine": {
            "name": "local_whisper_placeholder",
            "configured": False,
            "required": False,
        },
        "segments": [],
        "detected_speech_frequency": 0.0,
        "notes": "Reserved for future local speech transcription. No cloud transcription is used.",
    }


def _scene_labels(analysis: dict[str, Any]) -> list[str]:
    visual = analysis.get("visual", {})
    audio = analysis.get("audio", {})
    labels: list[str] = []
    brightness = float(visual.get("brightness_mean", 0.0))
    contrast = float(visual.get("contrast_mean", 0.0))
    motion = float(visual.get("motion_intensity", 0.0))
    scene_changes = int(visual.get("scene_changes", 0))
    audio_peaks = int(audio.get("audio_energy_peaks", 0))

    if audio.get("rms_level_db") is not None and motion < 18.0:
        labels.append("talking")
    if motion >= 18.0:
        labels.append("action")
    if contrast >= 45.0 and 55.0 <= brightness <= 190.0:
        labels.append("cinematic")
    if brightness < 70.0:
        labels.append("dark")
    if brightness > 185.0:
        labels.append("bright")
    if scene_changes >= 2 or (scene_changes >= 1 and audio_peaks >= 1):
        labels.append("fast_cut")
    if not labels:
        labels.append("cinematic")
    return labels


def _hook_moments(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    visual = analysis.get("visual", {})
    audio = analysis.get("audio", {})
    ocr = analysis.get("ocr", {})
    candidates: dict[float, dict[str, Any]] = {}

    def add(timestamp: float, reason: str, weight: int) -> None:
        key = round(max(0.0, timestamp), 1)
        item = candidates.setdefault(key, {"timestamp": key, "reasons": [], "score": 0})
        item["reasons"].append(reason)
        item["score"] += weight

    for timestamp in visual.get("motion_spike_timestamps", []):
        add(float(timestamp), "motion_spike", 25)
    for timestamp in visual.get("scene_change_timestamps", []):
        add(float(timestamp), "scene_change", 30)
    for timestamp in audio.get("audio_peak_timestamps", []):
        add(float(timestamp), "audio_peak", 20)

    text_frequency = float(ocr.get("detected_text_frequency", 0.0))
    if text_frequency > 0:
        add(0.0, "detected_text", min(20, int(text_frequency * 20)))

    if not candidates:
        add(0.0, "opening_context", 8)

    return sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:5]


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
    analysis["ocr"] = _ocr_placeholder(analysis["visual"])
    analysis["speech"] = _speech_placeholder(analysis["audio"])
    analysis["scene_labels"] = _scene_labels(analysis)
    analysis["hook_moments"] = _hook_moments(analysis)
    analysis.update(score_hook_potential(analysis))
    if math.isnan(float(analysis["score"])):
        analysis["score"] = 0
    return analysis
