#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.pipeline import process_once


def make_sample_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    root = Path.cwd()
    config = load_config(root)
    sample_path = config.inbox_dir / "smoke_sample.mp4"
    make_sample_video(sample_path)
    summary = process_once(config)

    index = json.loads(config.index_path.read_text(encoding="utf-8"))
    queue = json.loads(config.queue_path.read_text(encoding="utf-8"))
    processed = [video for video in index["videos"].values() if video["filename"] == sample_path.name]
    assert processed, "sample video was not registered"
    v13_ready = [
        video
        for video in processed
        if video.get("packages") and all("score" in clip for clip in video.get("clips", []))
    ]
    assert v13_ready, processed
    video = sorted(v13_ready, key=lambda item: item["updated_at"])[-1]
    assert video["status"] == "processed", video
    assert 3 <= len(video["clips"]) <= 5, video["clips"]
    assert len(video["captions"]) == len(video["clips"])
    assert len(video["subtitles"]) == len(video["clips"])
    assert len(video["packages"]) == len(video["clips"])
    assert queue["count"] >= len(video["clips"])
    for clip in video["clips"]:
        assert (root / clip["path"]).exists(), clip["path"]
        assert isinstance(clip["score"], int), clip
        assert "analysis" in clip, clip
    for caption in video["captions"]:
        assert (root / caption["path"]).exists(), caption["path"]
    for subtitle in video["subtitles"]:
        assert (root / subtitle["path"]).exists(), subtitle["path"]
        assert subtitle["status"] in {"pending_local_transcription", "no_audio"}, subtitle
    for package in video["packages"]:
        package_path = root / package["path"]
        assert package_path.exists(), package["path"]
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
        for key in ("hook", "caption", "hashtags", "subtitle_status", "suggested_title", "suggested_cta", "platform_notes"):
            assert key in package_payload, package_payload
    scored_entries = [entry for entry in queue["entries"] if entry["source_video_id"] == video["id"]]
    assert all(isinstance(entry.get("score"), int) for entry in scored_entries), scored_entries
    assert all(entry.get("package_path") for entry in scored_entries), scored_entries

    print(json.dumps({"smoke_test": "passed", "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
