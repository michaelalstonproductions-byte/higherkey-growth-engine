# HigherKey Operator OS Demo Checklist

## Before The Demo

- Confirm `ffmpeg` and `ffprobe` are available on `PATH`.
- Run `npm run qa:full` from the project root.
- Run `python3 scripts/generate_release_notes.py`.
- Build the unpacked app with `npm run dist:dir`.
- Confirm generated outputs are in the writable project folder, not inside app resources or `app.asar`.
- Put one short local video file in `content_inbox/` or keep a sample ready for the first-run flow.

## First Launch

- Start HigherKey Operator OS.
- Confirm the splash screen appears.
- Complete first-run setup:
  - choose the writable project folder
  - choose the content inbox
  - confirm FFmpeg health through diagnostics
  - open the Operator UI
- Open the About panel and confirm product name, version, build status, and local-first statement.

## Operator Walkthrough

- Click `Open Inbox` and add a local video file.
- Click `Run First Pipeline`.
- Confirm the queue, media bin, review monitor, and inspector populate from local JSON.
- Run `Re-cache Media` if thumbnails or waveform bars are missing.
- Run `Run Agents` to populate local agent status and recommendations.
- Run `Diagnostics` and confirm the Diagnostics panel updates.
- Approve one clip and export the approved review JSON.

## Release Candidate Checks

- Static browser workflow still opens `dashboard/review.html` from a local HTTP server.
- Electron bridge controls work in the packaged app.
- Watcher daemon behavior remains unchanged.
- No cloud APIs, social APIs, or publishing integrations are present.
- Runtime outputs stay in writable project paths.
