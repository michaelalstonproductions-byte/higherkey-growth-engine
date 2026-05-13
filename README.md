# HigherKey Autonomous Growth Engine

Local-first Python prototype for turning videos dropped into `content_inbox/` into reviewable vertical clip candidates.

## V1 Scope

- Scan or watch `content_inbox/` for local video files.
- Register videos into `analytics/video_index.json`.
- Generate 3-5 vertical 9:16 clip candidates with FFmpeg.
- Save generated clips in `clips/`.
- Generate placeholder hook/caption drafts in `captions/`.
- Write a human-review queue to `queue/review_queue.json`.
- Keep all processing local. No Instagram, TikTok, cloud, or external API integrations.

## Requirements

- Python 3.10+
- FFmpeg and ffprobe available on `PATH`

## Folder Layout

- `content_inbox/` - drop source videos here.
- `clips/` - generated vertical clips, grouped by video ID.
- `captions/` - placeholder caption JSON files, grouped by video ID.
- `queue/` - review queue JSON.
- `analytics/` - local video index JSON.
- `scripts/` - runnable prototype commands.
- `growth_engine/` - Python package.

## Run Once

```bash
python3 scripts/run_pipeline.py
```

## Watch The Inbox

```bash
python3 scripts/run_pipeline.py --watch --interval 5
```

Stop the watcher with `Ctrl-C`.

## Review Dashboard

Open the local dashboard after clips have been generated:

```bash
python3 -m http.server 8000
```

Then visit:

```text
http://localhost:8000/dashboard/review.html
```

The dashboard reads `queue/review_queue.json`, previews generated clips, displays caption drafts, and stores pending, approved, or rejected review status in your browser's local storage. It does not call social platforms or external APIs.

## Local Content Intelligence

Each generated clip is analyzed locally with FFmpeg-driven sampling. The V1.2 prototype estimates scene changes, motion intensity, brightness/contrast shifts, and audio energy peaks, then writes a deterministic hook score into each queue entry.

The dashboard sorts clips by score descending and displays the local analysis signals. Subtitle extraction is scaffolded with placeholder JSON files under `captions/subtitles/`; no transcription service or cloud AI API is used.

## Smoke Test

The smoke test creates a tiny synthetic video in `content_inbox/`, runs the pipeline, and checks for generated clips, captions, index, and queue output.

```bash
python3 scripts/smoke_test.py
```

## Notes

This is intentionally deterministic and local-first. Captions are placeholders for human review, and publishing integrations are out of scope for V1.
