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

Open the local Operator UI after clips have been generated:

```bash
python3 -m http.server 8000
```

Then visit:

```text
http://localhost:8000/dashboard/review.html
```

The Operator UI reads local JSON files, previews generated clips, displays caption packages, and stores pending, approved, or rejected review status in your browser's local storage. It does not call social platforms or external APIs.

V1.8 organizes the UI into tabs:

- `Queue` - review clips, scores, hook moments, labels, tags, and approval status.
- `Analytics` - local learning summary, top patterns, and recent performance imports.
- `Search` - filter by text, semantic tags, scene labels, clusters, status, and score.
- `Clusters` - inspect local topic clusters from `analytics/metadata_index.json`.
- `Exports` - review local approved-post export manifests.
- `Settings` - static placeholders for local config, optional AI status, jobs, and logs.

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

## Watcher Daemon

V1.9 adds a dependency-light local watcher daemon for continuous background processing:

```bash
python3 scripts/watch_daemon.py --interval 5
```

For a single tick during testing:

```bash
python3 scripts/watch_daemon.py --once
```

The daemon polls `content_inbox/`, queues new videos, processes queued jobs, and writes local status files:

- `analytics/jobs.json`
- `analytics/job_history.json`
- `analytics/pipeline_status.json`
- `analytics/activity_feed.json`
- `analytics/local_api_contract.json`

Job states are `queued`, `processing`, `completed`, `failed`, and `retrying`. To request reprocessing, write a local request to `queue/reprocess_requests.json`:

```json
{
  "requests": [
    { "source_path": "content_inbox/example.mp4" }
  ]
}
```

Then run:

```bash
python3 scripts/watch_daemon.py --once
```

The Operator UI Settings tab reads the live pipeline status, job history, and activity feed. The local API contract is a JSON placeholder for future desktop/mobile wrapping; no API server is required.

## Desktop App Shell

V2.0 wraps the existing Operator UI in a lightweight Electron shell without changing the Python engine. The static browser workflow still works.

Install Electron locally:

```bash
npm install
```

Run the desktop shell:

```bash
npm start
```

The Electron app starts a local static server, opens `dashboard/review.html`, and exposes a secure preload bridge with `contextIsolation: true` and `nodeIntegration: false`. Desktop-only controls in the Settings tab support local folder pickers, watcher start/stop, one daemon tick, drag/drop ingest into `content_inbox/`, and test notifications.

Project profiles, recent projects, active project path, folder settings, and watcher startup preference are stored locally in Electron's user data directory. No cloud APIs or social APIs are used.

## Operator Workflow UX

V2.1 turns the Operator UI into a workstation layout:

- Left media bin for queue navigation, batch selection, search, and status filtering.
- Center review monitor with video playback, approval controls, and queue priority.
- Right intelligence inspector for labels, tags, metadata, analytics, desktop bridge actions, and local session state.
- Bottom processing strip from local activity and job history files.

Keyboard shortcuts:

- `A` approve active clip
- `R` reject active clip
- `Right Arrow` or `N` next clip
- `Left Arrow` or `P` previous clip
- `Space` play/pause
- `E` export approved review JSON

Batch review state and queue priorities are stored in browser local storage. The static browser workflow and Electron bridge workflow both remain supported.

## Live Operator Intelligence

V2.2 adds live polling over local JSON files. The Operator UI auto-refreshes the review queue, metadata index, analytics outputs, pipeline status, activity feed, job history, exports, and video index without a manual page reload. Playback state, active clip, selection, review status, and priority state are preserved during refreshes.

The review monitor now includes local recommendation signals, hook-intensity heatmaps, and a two-clip comparison mode. Select two clips in the media bin to compare score, hook moments, labels, tags, title, and caption in the inspector.

Polling remains the default live mechanism. `config/live_events_contract.json` documents a local-only placeholder for future WebSocket or server-sent event wrappers.

## Local Multi-Agent Orchestration

V2.3 adds a deterministic local orchestration layer with specialized workers for ingest, clip generation, content intelligence, metadata indexing, analytics learning, recommendations, and export:

```bash
python3 scripts/run_orchestrator.py --once
```

The orchestrator writes dashboard-readable local JSON files:

- `analytics/agents.json`
- `analytics/agent_activity.json`
- `analytics/orchestration_graph.json`
- `analytics/recommendations.json`

Agent states are `idle`, `assigned`, `running`, `completed`, `failed`, and `disabled`. V2.3 executes sequentially; the orchestration graph includes a placeholder for future parallel execution. No cloud APIs or social APIs are used.

## Packaged Desktop Distribution

V2.4 prepares the Electron shell for local macOS packaging as `HigherKey Operator OS` with app id `com.higherkey.operatoros`.

Install dependencies:

```bash
npm install
```

Build an unpacked macOS app:

```bash
npm run dist:dir
```

Build an unsigned DMG:

```bash
npm run dist:unsigned
```

Clean package output:

```bash
npm run clean:dist
```

The packaged app bundles read-only application assets under Electron resources:

- `dashboard/`
- `growth_engine/`
- `scripts/`
- `config/`

Runtime files are not written into the app bundle or `app.asar`. On first packaged launch, HigherKey Operator OS creates a writable local project folder under Electron `userData` named `HigherKey Operator OS Project`. That folder contains `content_inbox/`, `analytics/`, `queue/`, `clips/`, `captions/`, `logs/`, `out/`, and `config/`. It also writes `HIGHERKEY_OPERATOR_OS_SETUP.md` and `config/desktop_runtime.json` so the active local project path is easy to find.

Use `File > Open Project` to switch the packaged app to another writable local project folder. Python scripts run from packaged resources with `PYTHONPATH` pointed at those resources and the selected project folder as the working directory, so generated outputs stay local and writable.

The DMG is intentionally unsigned for local testing. macOS Gatekeeper may require opening it through Finder's contextual Open flow or local security settings. Packaging does not add cloud APIs, publishing integrations, or social APIs.

## Native Media Preview Cache

V2.5 adds a local FFmpeg media preview cache for the Operator workspace:

```bash
python3 scripts/build_media_cache.py
```

Force a rebuild or cache only a few queue entries during testing:

```bash
python3 scripts/build_media_cache.py --force --limit 3
```

The builder reads `queue/review_queue.json`, generates preview assets under `out/media_cache/`, and writes `analytics/media_cache.json`. Each cached clip can include:

- a primary thumbnail
- timeline strip thumbnails
- a contact-sheet style timeline strip image
- normalized waveform/audio-energy bars when audio exists
- hook overlay positions for the Operator timeline

The Operator UI reads the cache manifest to show thumbnail grids, hover scrub previews, visual timeline strips, waveform bars, hook markers, and cache status indicators. In Electron, the `Re-cache Media` control runs the local cache builder through the same packaged-safe Python bridge. Static browser mode remains compatible; it simply reads existing cache JSON and preview files.

All preview generation is local and FFmpeg-based. Generated cache outputs stay in the selected writable project folder, not in packaged app resources or `app.asar`. No cloud APIs or social APIs are used.

## Diagnostics And Full QA

V2.6 adds local diagnostics and a one-command QA flow for stable demos and testing:

```bash
python3 scripts/run_diagnostics.py
python3 scripts/run_full_qa.py
```

The diagnostics system validates required tools (`python3`, `ffmpeg`, `ffprobe`, `node`, and `npm`), required writable folders, key JSON files, runtime path safety, and packaged app resources when a packaged build exists. It writes:

- `analytics/diagnostics.json`
- `analytics/qa_report.json`

JSON reads through the shared runtime helpers are hardened for corrupt or partial files. When malformed JSON is encountered, HigherKey copies the bad file to a timestamped `.corrupt-*` sibling and returns the caller's existing default shape so the app can continue running without destructive recovery.

The Operator UI includes a Diagnostics panel and Electron controls for `Diagnostics` and `Full QA`. Static browser mode remains compatible and reads the latest local diagnostics JSON files.

Packaged app QA checklist:

- Run `npm run dist:dir`.
- Confirm `dist/mac-arm64/HigherKey Operator OS.app` exists.
- Run `python3 scripts/run_full_qa.py`.
- Run `npm run electron:verify` separately for the desktop smoke path.
- Launch the packaged app and confirm the writable project folder contains `HIGHERKEY_OPERATOR_OS_SETUP.md` and `config/desktop_runtime.json`.
- Confirm generated files appear in the selected project folder, not app resources or `app.asar`.
- Confirm `analytics/diagnostics.json` and `analytics/qa_report.json` report `pass` or only expected warnings.

## Smoke Test

The smoke test creates a tiny synthetic video in `content_inbox/`, runs the pipeline, and checks for generated clips, captions, index, and queue output.

```bash
python3 scripts/smoke_test.py
```

## Notes

This is intentionally deterministic and local-first. Captions are placeholders for human review, and publishing integrations are out of scope for V1.
