# HigherKey Operator OS Client Handoff Guide

HigherKey Operator OS is a local-first desktop app for preparing short-form social clips from your own footage.

No cloud APIs, no social APIs, and no direct posting are configured. HigherKey prepares local upload folders; you upload manually.

## Install And Open

1. Open the newest DMG in `dist/`.
2. Drag `HigherKey Operator OS` into Applications if desired.
3. During development or testing, launch the newest local build with:

```bash
npm run app:open-latest
```

## Five-Step Workflow

1. **Import Footage**  
   Click `Import Footage` and choose `.mp4`, `.mov`, or `.m4v` files.

2. **Process Media**  
   Click `Import & Process` or `Process Media`. HigherKey creates clips, captions, thumbnails, color/audio readiness, recommendations, and local export prep.

3. **Review Clips**  
   Open `Queue`, review the generated clips, and approve the best ones.

4. **Export Social Packs**  
   Open `Social Exports`, choose the platform packs, and generate local folders.

5. **Upload Manually**  
   Open the export folder and manually upload the prepared video, caption, title, hashtags, notes, and thumbnail files.

## Demo Reset

Use `Reset Demo Workspace` to clear generated demo/test outputs before a client walkthrough. This preserves imported footage and project configuration.

## Troubleshooting

- **Import not working:** Use the desktop app, not a static browser tab. Choose MP4, MOV, or M4V files.
- **Processing taking long:** Leave the app open until the processing progress says ready for review.
- **No clips showing:** Confirm footage was imported, then click `Process Media`.
- **Export folder missing:** Generate social packs, then click `Open Social Exports`.
- **Need support:** Click `Create Support Package`. The package excludes original footage by default.
- **Need technical details:** Open `Diagnostics`.

## Beta Feedback

Use `BETA_READINESS_CHECKLIST.md` during the walkthrough. Feedback can be captured locally with:

```bash
python3 scripts/collect_client_feedback.py
```

## Local-Only Safety

All processing happens locally. HigherKey does not post to social platforms and does not call cloud APIs.
