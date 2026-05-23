# HigherKey Operator OS Client Handoff Guide

HigherKey Operator OS is a local-first desktop app for preparing short-form social clips from your own footage.

No cloud APIs, no social APIs, and no direct posting are configured. HigherKey prepares local upload folders; you upload manually.

## V7.0 What To Send

- The current HigherKey DMG or a pointer to the current DMG.
- `CLIENT_QUICK_START.md`
- `CLIENT_HANDOFF_GUIDE.md`
- `TRIAL_LIMITATIONS.md`
- `TRIAL_DELIVERY_CHECKLIST.md`
- `CLIENT_TRIAL_QA_SUMMARY.md`
- `out/client_delivery/CLIENT_DELIVERY_README.md`
- `out/client_delivery/CLIENT_DELIVERY_CHECKLIST.md`
- A generated handoff or trial package when intentionally built.
- Approved edited delivery packages when available.

## V7.0 What Not To Send

Do not send original private source media, `content_inbox/`, raw `clips/`, runtime databases, logs, token files, local connector config, local live publish policy, secrets, or credentials. Edited delivery packages exclude originals by default.

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
