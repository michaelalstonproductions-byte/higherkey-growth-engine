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

## Caption Packages

V1.3 prepares one local caption package per generated clip under `captions/packages/`. Each package includes the hook, caption, hashtags, subtitle status, suggested title, suggested CTA, platform notes for Instagram, TikTok, and YouTube Shorts, score details, and local file paths.

FFprobe is used to detect whether each clip has audio. Subtitle JSON remains a local placeholder designed for a future optional Whisper workflow, but Whisper is not required and no cloud transcription is used.

## Approved Post Export

V1.4 adds a local export lane for reviewed clips. In the dashboard, set clips to `Approved`, click `Export Approved JSON`, and save the downloaded file as:

```text
queue/approved_reviews.json
```

Then run:

```bash
python3 scripts/export_approved_posts.py
```

Approved posts are written to `out/approved_posts/<clip_id>/` with a final video copy, `caption.txt`, `hashtags.txt`, `title.txt`, `platform_notes.json`, and `manifest.json`. This only prepares local files; it does not publish to social platforms or call cloud APIs.

## Local Multimodal Understanding

V1.5 adds local-first architecture for multimodal understanding. FFmpeg frame sampling provides motion spikes, scene-change timestamps, brightness signals, and frame sampling metadata for future vision analysis. OCR and speech transcription are represented as placeholder schemas only; no OCR engine, Whisper install, cloud API, or external AI API is required.

Queue entries and caption packages include `hook_moments` and `scene_labels`. Hook moments are estimated from local motion spikes, scene changes, audio peaks, and future detected text frequency. Scene labels are simple rule-based tags such as `talking`, `action`, `cinematic`, `dark`, `bright`, and `fast_cut`.

## Local Performance Learning

V1.6 adds a manual analytics import and learning loop. Create a local JSON file with performance records:

```json
{
  "records": [
    {
      "queue_entry_id": "queue_example_clip_01",
      "views": 1200,
      "likes": 90,
      "comments": 12,
      "shares": 15,
      "saves": 20,
      "watch_time": 6200,
      "retention_percent": 71,
      "posted_at": "2026-05-12T09:00:00"
    }
  ]
}
```

Import it locally:

```bash
python3 scripts/import_performance_metrics.py analytics/performance_imports.json
```

The importer updates `analytics/performance_history.json`, `analytics/learning_summary.json`, and `analytics/top_patterns.json`. It compares predicted hook score with normalized manual performance, stores `learning_delta`, and ranks best hooks, scene labels, clip lengths, and posting patterns. The dashboard reads these local analytics files when present.

## Optional Local AI Metadata

V1.7 adds a searchable local metadata index with optional local AI adapters. By default it requires no new dependencies and uses deterministic local fallbacks for semantic tags, embeddings, similarity, topic clusters, and optimized titles:

```bash
python3 scripts/rebuild_metadata_index.py
```

This writes `analytics/metadata_index.json`. The dashboard reads that file to enable search and filters for semantic tags, scene labels, clusters, approval status, and score ranges.

Optional local AI can be enabled only if you have local tools installed:

```bash
python3 scripts/rebuild_metadata_index.py --enable-whisper --enable-ocr
```

`--enable-whisper` looks for a local `whisper` command. `--enable-ocr` looks for a local `tesseract` command. If they are missing, the indexer records `unavailable` and continues. No cloud APIs, external AI APIs, or social APIs are used.

## Smoke Test

The smoke test creates a tiny synthetic video in `content_inbox/`, runs the pipeline, and checks for generated clips, captions, index, and queue output.

```bash
python3 scripts/smoke_test.py
```

## Notes

This is intentionally deterministic and local-first. Captions are placeholders for human review, and publishing integrations are out of scope for V1.
