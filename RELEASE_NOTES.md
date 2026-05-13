# HigherKey Operator OS V2.7 Release Notes

Generated: 2026-05-13T04:10:48+00:00

Build status: `release-candidate`

App id: `com.higherkey.operatoros`

HigherKey Operator OS runs locally. No cloud APIs or social APIs are configured.

## V2.7 Release Candidate Desktop Demo

- Added startup splash screen for the Electron desktop shell.
- Added first-run setup flow for project folder, content inbox, FFmpeg health, diagnostics, and Operator UI handoff.
- Added About panel metadata, version badge, Open Content Inbox, and Run First Pipeline controls.
- Added release notes generation and demo checklist artifacts for repeatable desktop demonstrations.
- Added final app icon replacement notes and release build checklist documentation.

## Preserved Capabilities

- V1 local video ingest, clip generation, captions, queue review, and approved export workflow.
- V1.5 through V1.9 local content intelligence, metadata, learning, watcher daemon, and pipeline status JSON.
- V2.0 through V2.2 Electron shell, Operator workstation UI, live local JSON polling, recommendations, and comparisons.
- V2.3 deterministic local multi-agent orchestration.
- V2.4 packaged macOS desktop distribution using writable runtime project paths.
- V2.5 FFmpeg-based media preview cache.
- V2.6 diagnostics, safe JSON recovery, and one-command QA.

## Verification Checklist

- `npm run electron:verify`
- `npm run dist:dir`
- `npm run qa:full`
- `python3 -m py_compile growth_engine/*.py scripts/*.py`
- `python3 scripts/smoke_test.py`
- `python3 scripts/run_diagnostics.py`
- `python3 scripts/generate_release_notes.py`
- Dashboard JavaScript syntax check
- Packaged app/path verification
- External API scan

## Recent Git History

- `08f1d2f Add production diagnostics and QA hardening V2.6`
- `cdbf0da Add native media preview cache V2.5`
- `70d2adc Prepare packaged desktop distribution V2.4`
- `e310e44 Add local multi-agent orchestration layer V2.3`
- `1c4beb8 Add real-time intelligence and live preview engine V2.2`
- `e79f2c5 Build native operator workflow UX V2.1`
- `d9821ed Build Electron desktop shell V2.0`
- `9112441 Add continuous local processing and watcher daemon V1.9`
- `9d3656a Build Operator OS UI V1.8`
- `494bf0a Add local AI metadata and semantic indexing V1.7`
- `2c236f6 Add multimodal intelligence and local learning loop V1.5-V1.6`
- `a957496 Add approved post export lane V1.4`
