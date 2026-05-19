# HigherKey Operator OS Client Trial QA Summary

Version: V6.0 / 6.0.0

DMG:

- `dist/HigherKey Operator OS-6.0.0-arm64.dmg`

Trial package:

- Generate with `python3 scripts/package_trial_release.py`.
- Validate with `python3 scripts/validate_trial_package.py`.
- The package contains client docs, quick start, support notes, app info, a DMG pointer, and a feedback template.
- The package does not include private footage, imported media, generated clips, runtime databases, raw logs, tokens, or media cache files by default.

Client workflow:

1. Import Footage
2. Import & Process
3. Review and approve clips
4. Export Social Packs
5. Build Marketing / Creative / Command Center plans when useful
6. Use Autopilot dry-run for safe local preparation tasks
7. Upload manually

Release-candidate checks:

- Run `python3 scripts/run_release_candidate_audit.py`.
- Run `python3 scripts/run_client_rehearsal.py`.
- Confirm `analytics/release_candidate_audit.json` and `analytics/client_rehearsal_report.json` exist.
- Confirm `out/marketing/client_rehearsal_summary.md` exists.

Support workflow:

- Create a client-safe support package with `python3 scripts/create_issue_report.py --client-safe`.
- Support packages redact local paths by default.
- Original footage, generated clips, social export media, runtime databases, full logs, and tokens are excluded by default.

Known non-blocking warnings:

- Local trial readiness may show `needs_attention` when storage cleanup is recommended or QA has non-blocking warnings.
- macOS sandboxed launch checks can fail to write Application Support settings; launching with `npm run app:open-latest` in a normal GUI context verifies the packaged app.

Manual upload reminder:

- HigherKey prepares local platform folders.
- The client uploads those prepared files manually.
- No cloud APIs, social APIs, or direct posting APIs are configured.

What to test during the trial:

- Launch the app from the newest DMG.
- Import MP4, MOV, or M4V footage.
- Run Import & Process.
- Review generated clips.
- Approve at least one clip.
- Export social packs.
- Open the social export folder and inspect caption, hashtag, title, notes, checklist, thumbnail, and manifest files.
- Open Command and verify the daily action plan is readable.
- Open Autopilot and verify safe local tasks are visible without any social posting controls.
- Create a support package if anything looks wrong.
