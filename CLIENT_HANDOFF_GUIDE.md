# HigherKey Operator OS Client Handoff Guide

HigherKey Operator OS is a local-first desktop app for preparing short-form social clips from your own footage.

No social posting happens unless official connectors are configured, readiness checks pass, and approval gates are met. Manual upload remains available.

## V7.1 What To Send

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
- Trial issue queue and fix plan when intentionally generated after a client session.

## V7.1 What Not To Send

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
- **Need to send feedback:** Open `Trial Ops`, create the feedback template, import client notes locally, then build the issue queue.
- **Need technical details:** Open `Diagnostics`.

## Beta Feedback

Use `BETA_READINESS_CHECKLIST.md` during the walkthrough. Feedback can be captured locally with:

```bash
python3 scripts/collect_trial_feedback.py --template
python3 scripts/build_trial_issue_queue.py
```

## Local-Only Safety

All processing happens locally. HigherKey does not post to social platforms and does not call cloud APIs. Trial feedback is stored locally by default. Support packages are redacted and exclude private media, tokens, local connector config, runtime databases, and raw logs by default.
