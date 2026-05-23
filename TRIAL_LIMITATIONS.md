# HigherKey Operator OS Trial Limitations

HigherKey Operator OS is local-first trial software for client evaluation.

## V7.0 Launch Notes

- HigherKey prepares local assets, manifests, and packages.
- Manual upload remains the default fallback.
- Live posting requires official account connection, readiness checks, explicit approval, and controlled live publish gates.
- Editing is non-destructive. Original footage is not overwritten or deleted.
- Edited delivery packages include approved edited outputs and exclude original source media by default.
- No cloud editing APIs, scraping, browser automation, password login, or unauthorized social posting are enabled by default.

## What This Trial Does

- Imports local MP4, MOV, and M4V footage.
- Processes footage locally into clips, captions, thumbnails, recommendations, and manual-upload social export packs.
- Keeps runtime outputs in the selected local project folder.
- Creates client-safe support packages without original footage by default.

## What This Trial Does Not Do

- No cloud APIs.
- No social APIs.
- No direct posting APIs.
- No automatic upload to TikTok, Instagram, YouTube, or Facebook.
- No source media overwrite.

## Manual Upload Workflow

HigherKey prepares platform folders and files. The client uploads those files manually using the social platform’s normal upload flow.

## Recommended Test Footage

Use short real footage samples for the first trial pass:

- 15 seconds to 5 minutes per file.
- MP4, MOV, or M4V.
- Footage with visible subjects, action, or product moments works best.

## macOS Trial Note

The app may be unsigned during trial builds. macOS may ask you to approve opening the app. Use the newest DMG from `dist/` or the trial package pointer.

## Known Local Sandbox Note

Sandboxed verification can report a localhost or macOS AppKit launch warning in automated environments. Treat that as an environment limitation unless it reproduces when opening the packaged app directly.

## Support Package Guidance

If something fails, create a support package from inside the app. It includes client-safe state summaries and excludes original footage, private media, full logs, runtime DB files, and local tokens by default.
