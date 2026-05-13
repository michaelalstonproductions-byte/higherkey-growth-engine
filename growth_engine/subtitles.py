from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


def detect_audio(clip_path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index,codec_name,channels,sample_rate,duration",
                "-of",
                "json",
                str(clip_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        return {
            "has_audio": bool(streams),
            "audio_stream_count": len(streams),
            "audio_streams": streams,
            "probe_error": None,
        }
    except Exception as exc:  # noqa: BLE001 - audio probing should not block review package creation.
        return {
            "has_audio": False,
            "audio_stream_count": 0,
            "audio_streams": [],
            "probe_error": str(exc),
        }


def create_subtitle_placeholder(clip: dict[str, Any], captions_dir: Path, root: Path) -> dict[str, Any]:
    subtitle_dir = captions_dir / "subtitles" / clip["id"].rsplit("_clip_", 1)[0]
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    output_path = subtitle_dir / f"{clip['id']}_subtitles.json"
    audio = detect_audio(root / clip["path"])
    status = "pending_local_transcription" if audio["has_audio"] else "no_audio"
    payload = {
        "id": f"{clip['id']}_subtitles",
        "clip_id": clip["id"],
        "status": status,
        "method": "placeholder",
        "audio": audio,
        "transcription_engine": {
            "name": "whisper",
            "configured": False,
            "required": False,
            "notes": "Future local Whisper integration can populate segments without changing package schema.",
        },
        "segments": [],
        "notes": "Reserved for future local subtitle extraction. No cloud transcription is used.",
        "created_at": utc_now(),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "id": payload["id"],
        "path": relative_path(output_path, root),
        "status": payload["status"],
        "method": payload["method"],
        "has_audio": audio["has_audio"],
        "audio_stream_count": audio["audio_stream_count"],
    }


def create_subtitle_placeholders(clips: list[dict[str, Any]], captions_dir: Path, root: Path) -> list[dict[str, Any]]:
    return [create_subtitle_placeholder(clip, captions_dir, root) for clip in clips]
