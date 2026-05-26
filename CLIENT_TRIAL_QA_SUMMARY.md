# HigherKey Operator OS Client Trial QA Summary

Version: V7.6 / 7.6.0

## V7.6 Launch Checks

- Run `python3 scripts/build_client_delivery_manifest.py`.
- Run `python3 scripts/run_release_candidate_audit.py`.
- Run `python3 scripts/run_client_rehearsal.py`.
- Run handoff and trial package dry-runs.
- Confirm `analytics/client_delivery_manifest.json`, `analytics/client_launch_readiness.json`, and `analytics/client_delivery_checklist.json` exist.
- Confirm no tokens, secrets, local connector config, runtime DB, logs, raw clips, or original media are included in handoff by default.

Known local sandbox diagnostics warnings can remain warnings when QA exits 0 and external API scan reports `risky_hits: []`.

DMG:

- `dist/HigherKey Operator OS-7.6.0-arm64.dmg`

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
8. Use Trial Ops to collect local feedback, build the issue queue, and create a redacted support package

Release-candidate checks:

- Run `python3 scripts/run_release_candidate_audit.py`.
- Run `python3 scripts/run_client_rehearsal.py`.
- Confirm `analytics/release_candidate_audit.json` and `analytics/client_rehearsal_report.json` exist.
- Confirm `out/marketing/client_rehearsal_summary.md` exists.

Support workflow:

- Create a client-safe support package with `python3 scripts/create_issue_report.py --client-safe`.
- Create a local feedback template with `python3 scripts/collect_trial_feedback.py --template`.
- Build the issue queue with `python3 scripts/build_trial_issue_queue.py`.
- Support packages redact local paths by default.
- Original footage, generated clips, social export media, runtime databases, full logs, and tokens are excluded by default.

Known non-blocking warnings:

- Local trial readiness may show `needs_attention` when storage cleanup is recommended or QA has non-blocking warnings.
- macOS sandboxed launch checks can fail to write Application Support settings; launching with `npm run app:open-latest` in a normal GUI context verifies the packaged app.

Manual upload reminder:

- HigherKey prepares local platform folders.
- The client uploads those prepared files manually.
- No social posting happens unless official connectors are configured, readiness checks pass, and approval gates are met. Manual upload remains available.

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
- Open Trial Ops, build the issue queue, then run `python3 scripts/build_trial_patch_plan.py` to draft a local patch plan and client response notes.
- Build the patch execution board with `python3 scripts/build_patch_execution_board.py`.
- Mark patch status locally with `python3 scripts/update_patch_execution_status.py --status needs_verification --note "Verified locally"` when needed.
- Build draft release notes with `python3 scripts/build_client_release_notes.py`.
- Build the trial success report and scorecard with `python3 scripts/build_trial_success_report.py`.
- Build the client success dashboard and closeout report with `python3 scripts/build_client_success_dashboard.py`.
- Build the client success package dry run with `python3 scripts/package_client_success_delivery.py --dry-run`.
- Verify the package with `python3 scripts/verify_client_success_package.py`.
- Build the presentation overview with `python3 scripts/build_client_success_presentation.py`.
- Mark local fix status with `python3 scripts/update_trial_issue_status.py --status triaged --note "Reviewed locally"` when needed.
- Review response notes, client release notes, client update messages, trial success report, client trial summary, closeout report, client success package, presentation overview, and next engagement recommendation before sending. HigherKey does not upload feedback, create external tickets, send client messages, or mark issues fixed automatically.
- Confirm original media, raw clips, logs, runtime DB files, local connector config, token vault files, secrets, and credentials are excluded from the package.
