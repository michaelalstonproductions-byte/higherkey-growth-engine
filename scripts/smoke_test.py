#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.analytics import import_performance_metrics
from growth_engine.exporter import export_approved_posts
from growth_engine.local_ai import build_metadata_index
from growth_engine.jobs import daemon_tick
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
        assert isinstance(clip.get("hook_moments"), list), clip
        assert isinstance(clip.get("scene_labels"), list), clip
        assert "ocr" in clip["analysis"], clip["analysis"]
        assert "speech" in clip["analysis"], clip["analysis"]
    for caption in video["captions"]:
        assert (root / caption["path"]).exists(), caption["path"]
    for subtitle in video["subtitles"]:
        assert (root / subtitle["path"]).exists(), subtitle["path"]
        assert subtitle["status"] in {"pending_local_transcription", "no_audio"}, subtitle
    for package in video["packages"]:
        package_path = root / package["path"]
        assert package_path.exists(), package["path"]
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
        for key in ("hook", "caption", "hashtags", "subtitle_status", "suggested_title", "suggested_cta", "platform_notes", "hook_moments", "scene_labels"):
            assert key in package_payload, package_payload
    scored_entries = [entry for entry in queue["entries"] if entry["source_video_id"] == video["id"]]
    assert all(isinstance(entry.get("score"), int) for entry in scored_entries), scored_entries
    assert all(entry.get("package_path") for entry in scored_entries), scored_entries
    assert all(isinstance(entry.get("hook_moments"), list) for entry in scored_entries), scored_entries
    assert all(isinstance(entry.get("scene_labels"), list) for entry in scored_entries), scored_entries

    approved_entry = scored_entries[0]
    with tempfile.TemporaryDirectory() as temp_dir:
        approvals_path = Path(temp_dir) / "approved_reviews.json"
        output_dir = Path(temp_dir) / "approved_posts"
        approvals_path.write_text(
            json.dumps({"approved_entry_ids": [approved_entry["id"]]}, indent=2) + "\n",
            encoding="utf-8",
        )
        export_summary = export_approved_posts(root, approvals_path=approvals_path, output_dir=output_dir)
        assert export_summary["exported"] == 1, export_summary
        post_dir = output_dir / approved_entry["clip_id"]
        for filename in ("caption.txt", "hashtags.txt", "title.txt", "platform_notes.json", "manifest.json"):
            assert (post_dir / filename).exists(), filename
        assert any(post_dir.glob("*.mp4")), list(post_dir.iterdir())

        metrics_path = Path(temp_dir) / "performance_import.json"
        history_path = Path(temp_dir) / "performance_history.json"
        metrics_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "queue_entry_id": approved_entry["id"],
                            "views": 1200,
                            "likes": 90,
                            "comments": 12,
                            "shares": 15,
                            "saves": 20,
                            "watch_time": 6200,
                            "retention_percent": 71,
                            "posted_at": "2026-05-12T09:00:00",
                        }
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        analytics_summary = import_performance_metrics(root, metrics_path, history_path=history_path)
        assert analytics_summary["imported"] == 1, analytics_summary
        history = json.loads(history_path.read_text(encoding="utf-8"))
        assert "learning_delta" in history["records"][0], history
        assert (root / "analytics" / "learning_summary.json").exists()
        assert (root / "analytics" / "top_patterns.json").exists()

    metadata_summary = build_metadata_index(root)
    assert metadata_summary["indexed"] >= len(scored_entries), metadata_summary
    metadata_index = json.loads((root / "analytics" / "metadata_index.json").read_text(encoding="utf-8"))
    assert metadata_index["items"], metadata_index
    first_item = metadata_index["items"][0]
    for key in ("semantic_tags", "embedding", "similar_clips", "cluster_id", "optimized_title"):
        assert key in first_item, first_item
    daemon_summary = daemon_tick(config)
    assert "queued" in daemon_summary, daemon_summary
    for path in (
        config.analytics_dir / "jobs.json",
        config.analytics_dir / "job_history.json",
        config.analytics_dir / "pipeline_status.json",
        config.analytics_dir / "activity_feed.json",
        config.analytics_dir / "local_api_contract.json",
    ):
        assert path.exists(), path

    print(json.dumps({"smoke_test": "passed", "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
