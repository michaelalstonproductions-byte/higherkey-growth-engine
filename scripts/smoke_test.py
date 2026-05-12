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
    video = sorted(processed, key=lambda item: item["updated_at"])[-1]
    assert video["status"] == "processed", video
    assert 3 <= len(video["clips"]) <= 5, video["clips"]
    assert len(video["captions"]) == len(video["clips"])
    assert queue["count"] >= len(video["clips"])
    for clip in video["clips"]:
        assert (root / clip["path"]).exists(), clip["path"]
    for caption in video["captions"]:
        assert (root / caption["path"]).exists(), caption["path"]

    print(json.dumps({"smoke_test": "passed", "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
