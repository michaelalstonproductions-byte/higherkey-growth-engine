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

## Smoke Test

The smoke test creates a tiny synthetic video in `content_inbox/`, runs the pipeline, and checks for generated clips, captions, index, and queue output.

```bash
python3 scripts/smoke_test.py
```

## Notes

This is intentionally deterministic and local-first. Captions are placeholders for human review, and publishing integrations are out of scope for V1.
