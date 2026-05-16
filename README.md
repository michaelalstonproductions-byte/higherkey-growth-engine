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

This removes the previous unpacked app before rebuilding and writes `dist/latest-build.json`.

Build an unsigned DMG:

```bash
npm run dist:unsigned
```

This removes old `HigherKey Operator OS-*.dmg` and `.dmg.blockmap` files before packaging, so the DMG in `dist/` is replaced with the current local build every time.

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

## Release Candidate Desktop Demo

V2.7 polishes HigherKey Operator OS for release-candidate desktop demos. The Electron shell now shows a startup splash screen, runs an optional first-run setup flow, and exposes an About panel with product identity, version, build status, app id, and local-first status.

First-run setup guides the operator through a writable project folder, content inbox selection, FFmpeg health confirmation through diagnostics, and opening the Operator UI. The same runtime path rules from V2.4 remain in force: generated outputs stay in the selected writable project folder or Electron `userData`, never in app resources or `app.asar`.

Demo-focused Operator UI controls:

- `Open Inbox` opens the configured local content inbox.
- `Run First Pipeline` runs one local pipeline pass.
- `About` opens the desktop About panel in Electron or shows release info in static browser mode.
- Empty states now explain the local first-run path without requiring cloud or social integrations.

Generate release notes:

```bash
python3 scripts/generate_release_notes.py
```

This writes `RELEASE_NOTES.md`. A repeatable desktop demo script lives in `DEMO_CHECKLIST.md`, and final icon replacement notes live in `build/ICON_NOTES.md`.

DMG/release build checklist:

- Run `python3 scripts/generate_release_notes.py`.
- Run `npm run electron:verify`.
- Run `npm run qa:full`.
- Run `npm run dist:dir` and verify `dist/mac-arm64/HigherKey Operator OS.app`.
- Run `npm run dist:unsigned` when an unsigned DMG is needed; the script removes prior HigherKey DMGs first and writes `dist/latest-build.json`.
- Launch the unpacked app and complete first-run setup against a writable project folder.
- Confirm `dashboard/`, `electron/`, `growth_engine/`, `scripts/`, and `config/` are available from packaged resources.
- Confirm `content_inbox/`, `analytics/`, `queue/`, `clips/`, `captions/`, `logs/`, and `out/` are writable in the runtime project folder.
- Confirm diagnostics and QA reports are JSON-readable by the dashboard.
- Confirm no cloud APIs, social APIs, or publishing credentials are configured.

V2.7 verification note:

- In a sandboxed macOS verification path, `npm run electron:verify` can abort with `SIGABRT` during Electron/AppKit/HIServices application registration before product renderer logic runs.
- The same `electron:verify` path passed when run with GUI permission.
- `npm run dist:dir` passed.
- `npm run qa:full` passed.
- Treat sandbox-only `SIGABRT` as an environment limitation unless it reproduces when launching `dist/mac-arm64/HigherKey Operator OS.app` directly.

## Platform-Ready Social Export Packs

V2.8 adds a separate manual-upload export lane for TikTok, Instagram Reels, YouTube Shorts, and Facebook Reels:

```bash
python3 scripts/export_social_packs.py --approved-id <queue_entry_id>
```

Generated packs are written under `out/social_exports/<platform>/<clip_id>/` with a video copy, caption, hashtags, title, posting notes, upload checklist, optional thumbnail, and per-pack `manifest.json`. The root manifest is `out/social_exports/manifest.json`, and run history is stored in `analytics/social_export_history.json`.

Platform guidance lives in `config/social_platform_presets.json`. The Operator UI includes a `Social Exports` tab with batch export buttons by platform when running under Electron. Static browser mode remains compatible and shows the local command path.

This is manual upload workflow prep only. No direct posting APIs, cloud APIs, or social APIs are configured.

## Latest Local App Launch

During development and testing, launch the newest local app build from the repo root:

```bash
npm run app:open-latest
```

For path/version verification without launching the app:

```bash
npm run app:open-latest -- --dry-run
```

The launcher opens `dist/mac-arm64/HigherKey Operator OS.app`, prints the app path, checks `dist/latest-build.json` when present, and verifies `package.json` and `config/release.json` versions match. If testing from a DMG, run `npm run dist:unsigned` first so old HigherKey DMGs are removed and the remaining DMG is the current local build.

## V3.0 Runtime Infrastructure

V3.0 adds a local runtime infrastructure layer while preserving the existing JSON snapshots used by the dashboard.

- SQLite runtime DB: `analytics/runtime_state.db`
- Append-only events: `analytics/events.jsonl`
- Technical snapshot: `analytics/runtime_snapshot.json`
- Client-safe state: `analytics/client_state.json`
- Project manifest: `config/project_manifest.json`
- Runtime lock: `analytics/runtime.lock`

Useful commands:

```bash
python3 scripts/init_project_manifest.py
python3 scripts/backfill_runtime_db.py
python3 scripts/build_runtime_snapshot.py
python3 scripts/run_maintenance.py --dry-run
python3 scripts/run_runtime_worker.py --once
```

The runtime DB is a local SQLite compatibility index over existing project JSON files. JSON outputs remain the app-facing compatibility layer and are not removed. Maintenance and worker scripts are deterministic, local-only, and do not call cloud, social, or posting APIs.

## V3.1 Task Queue

V3.1 adds a durable local task queue and scheduling metadata layer in `analytics/runtime_state.db`.

Task tables:

- `task_queue`
- `task_attempts`
- `task_dependencies`
- `task_schedules`

Task statuses are `queued`, `scheduled`, `running`, `completed`, `failed`, `cancelled`, `retrying`, and `blocked`. Priorities are `high`, `normal`, and `low`.

Useful commands:

```bash
python3 scripts/enqueue_full_media_prep.py
python3 scripts/run_task_worker.py --once
python3 scripts/run_task_worker.py --once --dry-run
python3 scripts/schedule_tasks.py
python3 scripts/build_task_snapshot.py
```

Task snapshots are written to `analytics/task_summary.json` and `analytics/client_tasks.json`. Scheduled automation metadata is written to SQLite and mirrored to `analytics/task_schedules.json`; no OS launch daemon is installed. The queue remains local-only and does not add cloud APIs, social APIs, or direct posting integrations.

## V3.2 Worker Runtime

V3.2 turns the durable task queue into a local worker runtime. Worker lifecycle status is written to `analytics/worker_runtime_status.json`, and lifecycle history is written to `analytics/worker_runtime_history.json`.

Worker states:

- `stopped`
- `starting`
- `idle`
- `running`
- `paused`
- `stopping`
- `failed`
- `stale`

Worker commands:

```bash
python3 scripts/manage_worker.py status
python3 scripts/manage_worker.py once
python3 scripts/manage_worker.py start
python3 scripts/manage_worker.py pause
python3 scripts/manage_worker.py resume
python3 scripts/manage_worker.py stop
python3 scripts/manage_worker.py restart
python3 scripts/manage_worker.py cleanup-stale
```

The local setting `worker.auto_start` defaults to `false`. When enabled in Electron settings, the app starts the worker on launch while avoiding duplicate worker processes. Queued Import & Process mode is available through the Electron bridge as an additive path: it imports footage, enqueues the Full Media Prep task chain, and runs the worker without removing the existing synchronous process path.

`analytics/client_tasks.json` contains client-safe task progress, stage, and message fields. Raw stdout/stderr stays in technical task reports and diagnostics.

## V3.3 Local API Service

V3.3 adds an optional local-only API service so Electron and future UI surfaces can query stable endpoints while the existing JSON snapshot workflow remains supported.

Run the API:

```bash
python3 scripts/run_local_api.py --once-health
python3 scripts/run_local_api.py --host 127.0.0.1 --port 8765 --write-status
```

Status files:

- `analytics/local_api_status.json`
- `analytics/local_api_history.json`

Read endpoints include `/health`, `/state/client`, `/state/runtime`, `/tasks`, `/tasks/summary`, `/worker/status`, `/events/recent`, `/project/manifest`, `/media/summary`, `/pipeline/status`, `/diagnostics`, `/social/exports`, `/schools/color`, and `/schools/audio`.

Safe local POST endpoints include `/tasks/enqueue/full-media-prep`, `/worker/once`, `/worker/start`, `/worker/stop`, `/worker/pause`, `/worker/resume`, `/maintenance/run`, `/snapshot/build`, and `/repair/run`.

The API binds only to `127.0.0.1`, rejects non-local requests, exposes no arbitrary command execution or file read endpoints, and does not add cloud APIs, social APIs, or direct posting integrations. The Electron setting `local_api.auto_start` defaults to `false`.

## V3.4 Project Lifecycle

V3.4 adds local project lifecycle infrastructure for backup, restore, reset, archive, validation, and portable handoff. All commands are local-only and preserve source media unless an explicit destructive flag is provided.

Useful commands:

```bash
python3 scripts/backup_project.py --dry-run
python3 scripts/backup_project.py
python3 scripts/restore_project.py out/project_backups/<backup>.zip --dry-run
python3 scripts/reset_demo_workspace.py --soft --dry-run
python3 scripts/archive_project_artifacts.py --dry-run
python3 scripts/validate_project.py
python3 scripts/project_size_report.py
```

Backup output goes under `out/project_backups/` and writes `analytics/project_backup_report.json`. Backups include project manifest, runtime DB, event log, client snapshots, queue, clips, captions, social exports, approved posts, analytics reports, and config JSON. Source media in `content_inbox/` is excluded unless `--include-source-media` is passed. Large media cache files are excluded unless `--include-cache` is passed.

Restore validates `backup_manifest.json`, refuses to overwrite existing targets unless `--force` is passed, writes `analytics/project_restore_report.json`, refreshes `config/project_manifest.json`, and rebuilds runtime snapshots.

Demo reset modes:

- `--soft`: clears generated outputs while keeping `content_inbox/`.
- `--hard`: clears generated outputs and source inbox only with `--confirm-delete-source-media`.
- `--archive-first`: creates a backup before reset.

Lifecycle reports:

- `analytics/project_validation_report.json`
- `analytics/project_size_report.json`
- `analytics/demo_reset_report.json`
- `analytics/project_archive_report.json`

The task queue can run lifecycle task types, and the local API exposes lifecycle endpoints under `/project/*`. No cloud APIs, social APIs, or posting APIs are added.

## V3.5 Observability

V3.5 adds local observability, client-safe metrics, and an append-only audit trail. It is local-only and does not add cloud APIs, social APIs, or direct posting integrations.

Build reports:

```bash
python3 scripts/build_observability_report.py
```

Generated files:

- `analytics/runtime_metrics.json`: technical runtime metrics for tasks, worker state, pipeline health, media counts, school status, diagnostics, runtime DB size, project size, event counts, and recent warnings.
- `analytics/client_metrics.json`: client-friendly metrics with health labels, task status, media summary, and next action.
- `analytics/audit_log.jsonl`: append-only audit trail for project, media, pipeline, task, worker, export, diagnostics, QA, maintenance, and settings events.
- `analytics/observability_report.json`: aggregated local observability report from events, audit, worker/task history, maintenance, QA, repair, and pipeline status.
- `analytics/client_observability.json`: client-safe observability summary without raw stderr, tracebacks, or large JSON blocks.
- `config/error_taxonomy.json`: local mapping for common runtime categories such as missing media, path mismatch, stale workers, API offline, diagnostics warnings, and school warnings.

The runtime health score is a local 0-100 score derived from diagnostics, valid production clips, task failures, worker state, missing media, runtime DB health, local API state, and project validation. It is mirrored into `analytics/client_state.json` and `analytics/client_metrics.json`.

Local API observability endpoints:

- `GET /metrics/runtime`
- `GET /metrics/client`
- `GET /audit/recent`
- `GET /observability/report`
- `GET /health/score`

Maintenance now includes observability report generation. Full QA includes bounded observability, audit, taxonomy, and local API metrics checks.

## V3.6 State Reconciliation

V3.6 adds local state reconciliation and self-healing checks across SQLite runtime state, JSON snapshots, generated clips, captions, media cache, social exports, school reports, task snapshots, event logs, and audit logs.

Run reconciliation:

```bash
python3 scripts/reconcile_runtime_state.py --dry-run
python3 scripts/reconcile_runtime_state.py --dry-run --json
python3 scripts/reconcile_runtime_state.py --apply
```

Generated files:

- `config/state_contract.json`: source-of-truth contract for DB tables, required folders, runtime files, client-facing files, generated files, and ignored runtime files.
- `analytics/state_reconciliation_report.json`: technical reconciliation report with issue categories and repairable flags.
- `analytics/client_integrity.json`: client-safe integrity summary with status, warnings, and next action.
- `analytics/quarantine_report.json`: metadata-only quarantine manifest for stale references.

Dry run is the default and only reports issues. Apply mode is non-destructive: it backfills runtime DB rows from JSON, rebuilds client/runtime/task/observability snapshots, marks safe metadata issues, and writes quarantine manifests. It does not delete real media, overwrite source footage, or move original footage.

Local API reconciliation endpoints:

- `GET /state/integrity`
- `GET /state/reconciliation`
- `POST /state/reconcile`
- `POST /state/reconcile/apply`

Maintenance includes a reconciliation dry-run. Full QA includes state contract loading, reconciliation dry-run, client integrity generation, and a temp-project apply fixture.

## V3.7 Local Security

V3.7 adds local security policy, permission summaries, confirmation receipts, and runtime safety checks. It remains local-only and does not add cloud APIs, social APIs, direct posting APIs, arbitrary command execution, or arbitrary file access.

Run security checks:

```bash
python3 scripts/run_security_check.py
```

Generated files:

- `config/security_policy.json`: local security policy for allowed API hosts, protected project roots, runtime directories, import extensions, action allowlists, confirmation requirements, and token settings.
- `analytics/security_report.json`: security check report with protected path rejection, import validation, local API safety, and action allowlist results.
- `analytics/permissions_manifest.json`: client-readable summary of writable runtime directories, read-only app directories, protected directories, enabled actions, and disabled unsafe capabilities.
- `analytics/confirmation_receipts.jsonl`: append-only confirmation receipts for sensitive local actions such as restore, reset, archive, reconcile apply, backup, and cache deletion.

Protected path rules:

- The project root cannot be `content_inbox`.
- The project root cannot be `/`, `/Users`, `/Applications`, `/System`, `/Library`, or the home folder directly.
- Runtime writes must stay inside the active project root.
- Imports are limited to `.mp4`, `.mov`, and `.m4v`, with duplicate handling and file size validation.

Local API security:

- The local API binds to `127.0.0.1` by default and rejects non-localhost requests.
- POST actions are checked against the security policy allowlist.
- Optional local token support is available through `config/security_policy.json`; tokens are stored locally and are not exposed in normal client state.
- Security endpoints:
  - `GET /security/status`
  - `POST /security/validate-path`
  - `POST /security/rotate-token`

Maintenance now runs the security check and updates `analytics/permissions_manifest.json`. Observability, diagnostics, and client state include client-safe security status labels: `Secure`, `Needs Attention`, or `Unsafe Configuration`.

## V3.8 Storage and Retention

V3.8 adds local data retention, cache reporting, cleanup planning, generated artifact archiving, and workspace storage health. It is local-only and does not add cloud APIs, social APIs, direct posting APIs, arbitrary file cleanup, or destructive source-media behavior.

Run storage tools:

```bash
python3 scripts/manage_storage.py report
python3 scripts/manage_storage.py plan --dry-run
python3 scripts/manage_storage.py archive --dry-run
python3 scripts/manage_storage.py apply --apply --confirm --category media_cache
```

Generated files:

- `config/retention_policy.json`: safe retention rules for media cache, logs, QA reports, diagnostics, school reports, quarantine manifests, audio previews, archives, dist artifacts, source footage, and runtime DB files.
- `analytics/cache_report.json`: technical storage report with category sizes, counts, age, and protection status.
- `analytics/cleanup_plan.json`: dry-run cleanup plan with eligible generated files, protected items, and planned archive/delete actions.
- `analytics/cleanup_history.json`: local history of cleanup runs.
- `analytics/client_storage.json`: client-safe storage summary with labels such as `Storage Healthy`, `Cleanup Recommended`, and `Storage Needs Attention`.
- `analytics/archive_manifest.json` and `analytics/archive_history.json`: local archive manifests for generated artifacts moved under `out/archives/`.

Safety rules:

- Cleanup is dry-run by default.
- Apply mode requires both `--apply` and `--confirm`.
- Original imported footage in `content_inbox/` is protected and is never deleted automatically.
- Approved exports and social export packs are protected by default.
- Runtime DB and project manifest are protected by default.
- No cleanup action may operate outside the active project root.

Local API storage endpoints:

- `GET /storage/report`
- `GET /storage/client`
- `GET /cleanup/plan`
- `POST /cleanup/plan`
- `POST /cleanup/apply`
- `POST /cleanup/archive`
- `POST /storage/vacuum-db`

Maintenance now builds the storage report and cleanup plan dry-run. Full QA includes retention policy loading, storage report generation, cleanup plan generation, archive dry-run, DB vacuum dry-run, and a temp-project fixture proving original footage is protected.

## V3.9 Upgrade and Migration Safety

V3.9 adds local upgrade planning, migration checks, rollback planning, data contract validation, and launch preflight. It is local-only and preserves original footage, JSON compatibility snapshots, runtime DB state, task queue state, worker state, local API behavior, reconciliation, security, and storage retention.

Run upgrade checks:

```bash
python3 scripts/upgrade_project.py --check
python3 scripts/upgrade_project.py --plan
python3 scripts/validate_data_contract.py
python3 scripts/run_launch_preflight.py
```

Generated files:

- `config/version_contract.json`: app/schema compatibility contract, required runtime files, DB tables, config files, scripts, deprecated files, and migration notes.
- `analytics/upgrade_plan.json`: dry-run upgrade plan with required migrations and compatibility status.
- `analytics/upgrade_report.json`: upgrade apply/check report. Apply mode is explicit and safe-only.
- `analytics/client_upgrade_status.json`: client-safe upgrade status without raw traceback or stdout/stderr.
- `analytics/rollback_plan.json`: rollback metadata showing changed files, DB migrations, config updates, backup reference, and reversibility.
- `analytics/pre_upgrade_backup_manifest.json`: local pre-upgrade backup recommendation and manifest.
- `analytics/data_contract_report.json`: validation report for version/state/security/retention/project contracts, runtime DB schema, task queue schema, local API contract, and client snapshots.
- `analytics/launch_preflight.json`: launch-readiness report for project manifest, runtime DB, version match, security, storage, reconciliation, client state, worker state, and stale locks.

Safety rules:

- Upgrade planning is dry-run by default.
- `--apply` is required to run migrations.
- Migrations are idempotent and local-only.
- Original imported footage is never deleted or overwritten.
- Rollback planning is written before apply mode, but automatic restore is not performed unless explicitly added later.

Local API upgrade endpoints:

- `GET /upgrade/status`
- `GET /upgrade/plan`
- `POST /upgrade/check`
- `POST /upgrade/apply`
- `GET /launch/preflight`
- `GET /contracts/data`

Maintenance now includes upgrade check, data contract validation, and launch preflight in dry-run mode.

## V4.0 Client Workflow

V4.0 adds a client-facing workflow layer over the V3.9 local runtime. The infrastructure remains available in Diagnostics and Settings, while the main Dashboard focuses on a simple production path:

1. Import Footage
2. Process Media
3. Review Clips
4. Approve Best Clips
5. Export Social Packs
6. Upload Manually

Build the workflow snapshot:

```bash
python3 scripts/build_client_workflow.py
```

Generated file:

- `analytics/client_workflow.json`: client-safe workflow state with current step, completed steps, next action, message, warnings summary, and local counts.

Client usage:

- Click `Import Footage` to choose local `.mp4`, `.mov`, or `.m4v` files. The app copies them into the active project.
- Click `Import & Process` to import files and run local media preparation.
- Click `Process Media` to create clips, previews, color/audio analysis, and recommendations from existing imported footage.
- Review clips in Queue or Media, approve the best clips, then export social packs.
- Upload manually from the prepared local folders. No direct posting APIs are configured.

Technical runtime details such as runtime DB, task queue, local API, reconciliation, upgrade checks, storage retention, and security remain in Diagnostics/Settings.

## V4.1 Client Demo Workflow

V4.1 adds demo-ready workflow polish on top of the V4.0 client layer. The main app now emphasizes a five-step demo path:

1. Import Footage
2. Process Media
3. Review Clips
4. Export Social Packs
5. Upload Manually

Client demo controls:

- `Import Footage`: opens the native desktop file picker and copies supported videos into the active project.
- `Import & Process`: imports selected videos and runs local preparation.
- `Process Media`: runs local clip creation, previews, color/audio analysis, recommendations, and social-pack prep.
- `Reset Demo Workspace`: safely clears generated demo/test outputs while preserving imported footage and project configuration.
- `Open Social Exports`: opens the prepared manual-upload folders.

The Dashboard includes a Demo Import Wizard, import success modal, processing progress modal, and demo checklist. Technical logs remain in Diagnostics/Settings.

## V4.2 Client Handoff

V4.2 adds a clean client handoff package and demo-project setup tools.

Create a clean demo project folder:

```bash
python3 scripts/create_demo_project.py --target out/demo_project_handoff
```

Preview the demo project setup without writing files:

```bash
python3 scripts/create_demo_project.py --dry-run
```

Build a client handoff package:

```bash
python3 scripts/package_client_handoff.py
```

Preview the handoff package:

```bash
python3 scripts/package_client_handoff.py --dry-run
```

Generated handoff folder:

- `out/client_handoff/CLIENT_HANDOFF_GUIDE.md`
- `out/client_handoff/BETA_READINESS_CHECKLIST.md`
- `out/client_handoff/DEMO_CHECKLIST.md`
- `out/client_handoff/RELEASE_NOTES.md`
- `out/client_handoff/app_info.json`
- `out/client_handoff/latest_dmg_pointer.json`
- `out/client_handoff/quick_start.txt`
- `out/client_handoff/support_note.txt`

Client demo mode defaults live in `config/client_demo.json`. The handoff package points to the newest DMG in `dist/` and does not copy private runtime data or source footage by default.

## V4.3 Client Beta Handoff

V4.3 prepares a real client beta handoff without adding cloud services or direct posting.

Client beta files:

- `BETA_READINESS_CHECKLIST.md`: install, launch, import, process, review, export, upload, diagnostics, and feedback checklist.
- `CLIENT_HANDOFF_GUIDE.md`: client-safe guide for opening the app and running the manual-upload workflow.
- `out/client_handoff/`: generated handoff package with quick start, release notes, checklist docs, app info, latest DMG pointer, and support note.

Capture local beta feedback:

```bash
python3 scripts/collect_client_feedback.py --dry-run
python3 scripts/collect_client_feedback.py --client-name "Client Name" --overall-rating 5 --notes "Demo notes"
```

Create a client-safe support package:

```bash
python3 scripts/create_issue_report.py --dry-run
python3 scripts/create_issue_report.py
```

Generated support folder:

- `out/client_issue_report/issue_report.json`
- `out/client_issue_report/issue_report.txt`
- client-safe state summaries when available

Issue reports exclude original footage, private generated media, full logs, runtime DB files, and local tokens by default. In the app, use `Create Support Package` and `Open Support Package` from client troubleshooting areas.

## V4.4 Client Trial Package

V4.4 prepares a clean local trial package for a real client without copying private footage or runtime media.

Build the trial package:

```bash
python3 scripts/package_trial_release.py
```

Preview the package without writing files:

```bash
python3 scripts/package_trial_release.py --dry-run
```

Optionally copy the newest DMG into the package:

```bash
python3 scripts/package_trial_release.py --include-dmg
```

Generated trial folder:

- `out/trial_release/CLIENT_HANDOFF_GUIDE.md`
- `out/trial_release/CLIENT_QUICK_START.md`
- `out/trial_release/BETA_READINESS_CHECKLIST.md`
- `out/trial_release/DEMO_CHECKLIST.md`
- `out/trial_release/RELEASE_NOTES.md`
- `out/trial_release/TRIAL_LIMITATIONS.md`
- `out/trial_release/app_info.json`
- `out/trial_release/latest_dmg_pointer.json`
- `out/trial_release/quick_start.txt`
- `out/trial_release/support_note.txt`
- `out/trial_release/trial_limitations.txt`
- `out/trial_release/client_feedback_template.json`

Build a readiness report:

```bash
python3 scripts/build_trial_readiness_report.py
```

Generated readiness file:

- `analytics/trial_readiness_report.json`

What to send to a client:

- the newest DMG from `dist/`
- the contents of `out/trial_release/`
- `CLIENT_QUICK_START.md`
- `TRIAL_LIMITATIONS.md`

Trial workflow reminder:

1. Open the app.
2. Import footage.
3. Import & Process.
4. Review and approve clips.
5. Export social packs.
6. Upload manually.

HigherKey remains local-first. No cloud APIs, social APIs, or direct posting APIs are configured.

## V4.5 Trial Delivery and Feedback

V4.5 adds the final local handoff loop for client trials: package validation, feedback capture, and client-safe support reports.

Delivery checklist:

```bash
npm run dist:unsigned
python3 scripts/package_trial_release.py
python3 scripts/validate_trial_package.py
python3 scripts/build_trial_readiness_report.py
```

What to send:

- the newest `dist/HigherKey Operator OS-*-arm64.dmg`
- `out/trial_release/`
- `CLIENT_QUICK_START.md`
- `TRIAL_LIMITATIONS.md`
- `TRIAL_DELIVERY_CHECKLIST.md`

Client feedback stays local:

```bash
python3 scripts/collect_client_feedback.py --template
python3 scripts/collect_client_feedback.py --interactive
python3 scripts/collect_client_feedback.py --export-summary
```

Client-safe support package:

```bash
python3 scripts/create_issue_report.py --client-safe
```

Support packages exclude original footage, social exports, imported media, full runtime databases, private tokens, and unredacted local paths by default. HigherKey remains local-first with manual upload only.

## V4.7 Final Client Trial QA

V4.7 adds a final handoff verification layer for client trials. It does not add cloud services, social APIs, direct posting, or new runtime behavior.

Final trial QA:

```bash
python3 scripts/run_client_trial_qa.py
python3 scripts/check_client_language.py
python3 scripts/build_trial_readiness_report.py
```

Build and validate the trial package:

```bash
npm run dist:unsigned
python3 scripts/package_trial_release.py
python3 scripts/validate_trial_package.py
```

What to send to a client:

- `dist/HigherKey Operator OS-4.7.0-arm64.dmg`
- `out/trial_release/`
- `CLIENT_QUICK_START.md`
- `CLIENT_HANDOFF_GUIDE.md`
- `TRIAL_LIMITATIONS.md`
- `TRIAL_DELIVERY_CHECKLIST.md`
- `CLIENT_TRIAL_QA_SUMMARY.md`

Support package:

```bash
python3 scripts/create_issue_report.py --client-safe
```

Feedback collection:

```bash
python3 scripts/collect_client_feedback.py --template
python3 scripts/collect_client_feedback.py --interactive
python3 scripts/collect_client_feedback.py --export-summary
```

Known non-blocking warning: sandboxed macOS launch checks can fail when the sandbox cannot write Application Support settings. Use `npm run app:open-latest` in the normal GUI environment to verify the packaged app. Trial readiness may also show `needs_attention` for non-blocking QA or storage cleanup warnings.

Manual upload reminder: HigherKey prepares local platform folders. The client uploads manually. No cloud APIs, social APIs, or direct posting APIs are configured.

## Smoke Test

The smoke test creates a tiny synthetic video in `content_inbox/`, runs the pipeline, and checks for generated clips, captions, index, and queue output.

```bash
python3 scripts/smoke_test.py
```

## Notes

This is intentionally deterministic and local-first. Captions are placeholders for human review, and publishing integrations are out of scope for V1.
