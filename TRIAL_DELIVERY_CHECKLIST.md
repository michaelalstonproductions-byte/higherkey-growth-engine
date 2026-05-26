# HigherKey Operator OS Trial Delivery Checklist

Use this checklist before handing a trial build to a client.

## V7.6 Client Delivery

- [ ] Run Launch Room > Run Launch Audit.
- [ ] Run Launch Room > Run Client Rehearsal.
- [ ] Build the client delivery manifest.
- [ ] Build or dry-run client handoff.
- [ ] Build or dry-run trial package.
- [ ] Verify edited delivery package when edited assets are included.
- [ ] Confirm manual upload fallback is visible.
- [ ] Confirm optional social connection language does not imply automatic posting.
- [ ] Confirm Trial Ops feedback template, issue queue, and redacted support package flow are available.
- [ ] Confirm Trial Ops patch execution board, verification checklist, and client release note drafts are available.
- [ ] Confirm Trial Ops trial success report, scorecard, internal analysis, and next trial plan are available.
- [ ] Confirm Trial Ops client success dashboard, trial closeout report, operator checklist, and next engagement recommendation are available.
- [ ] Confirm original source media is not included by default.
- [ ] Confirm token, secret, connector local config, live publish local policy, runtime DB, logs, and raw clips are not included.

## Build And QA

- [ ] Rebuild the unsigned DMG with `npm run dist:unsigned`.
- [ ] Run `npm run qa:full`.
- [ ] Run `python3 scripts/run_release_candidate_audit.py`.
- [ ] Run `python3 scripts/run_client_rehearsal.py`.
- [ ] Run `python3 scripts/build_trial_readiness_report.py`.
- [ ] Generate the trial package with `python3 scripts/package_trial_release.py`.
- [ ] Validate the trial package with `python3 scripts/validate_trial_package.py`.
- [ ] Open the latest app with `npm run app:open-latest`.

## Client Workflow Checks

- [ ] Test **Import Footage** with one short MP4, MOV, or M4V.
- [ ] Test **Import & Process**.
- [ ] Review clips.
- [ ] Approve at least one clip when available.
- [ ] Test social export pack generation.
- [ ] Open the social export folder.
- [ ] Open **Command** and verify today's plan.
- [ ] Open **Marketing** and verify strategy/creative/growth views.
- [ ] Open **Autopilot** and verify safe dry-run/manual approval language.
- [ ] Confirm manual upload language is visible.

## Support And Safety

- [ ] Create a support package.
- [ ] Confirm the support package excludes original footage.
- [ ] Confirm the trial package excludes private media and runtime DB files.
- [ ] Confirm `latest_dmg_pointer.json` points to the current DMG.
- [ ] Confirm `analytics/release_candidate_audit.json` exists.
- [ ] Confirm `analytics/client_rehearsal_report.json` exists.
- [ ] Confirm `analytics/client_feedback_inbox.json`, `analytics/client_feedback_summary.json`, `analytics/client_trial_status.json`, and `analytics/client_issue_queue.json` exist after Trial Ops checks.
- [ ] Confirm `out/client_delivery/TRIAL_ISSUE_QUEUE.md` and `out/client_delivery/TRIAL_FIX_PLAN.md` exist.
- [ ] Build the trial patch plan with `python3 scripts/build_trial_patch_plan.py`.
- [ ] Confirm `analytics/feedback_triage_report.json`, `analytics/client_patch_plan.json`, `analytics/client_response_notes.json`, `analytics/trial_fix_backlog.json`, and `analytics/trial_risk_summary.json` exist.
- [ ] Confirm `out/client_delivery/TRIAL_PATCH_PLAN.md`, `out/client_delivery/CLIENT_RESPONSE_NOTES.md`, and `out/client_delivery/TRIAL_RISK_SUMMARY.md` exist.
- [ ] Build the patch execution board with `python3 scripts/build_patch_execution_board.py`.
- [ ] Confirm `analytics/patch_execution_board.json`, `analytics/patch_verification_plan.json`, and `analytics/client_patch_status.json` exist.
- [ ] Confirm `out/client_delivery/PATCH_EXECUTION_BOARD.md` and `out/client_delivery/PATCH_VERIFICATION_CHECKLIST.md` exist.
- [ ] Build client release notes with `python3 scripts/build_client_release_notes.py`.
- [ ] Confirm `analytics/patch_release_notes.json`, `analytics/client_release_notes.json`, `out/client_delivery/CLIENT_RELEASE_NOTES.md`, `out/client_delivery/CLIENT_UPDATE_MESSAGE.md`, and `out/client_delivery/INTERNAL_PATCH_NOTES.md` exist.
- [ ] Build the trial success report with `python3 scripts/build_trial_success_report.py`.
- [ ] Confirm `analytics/trial_success_report.json`, `analytics/client_trial_success_report.json`, `analytics/internal_trial_analysis.json`, `analytics/next_trial_plan.json`, and `analytics/client_trial_scorecard.json` exist.
- [ ] Confirm `out/client_delivery/TRIAL_SUCCESS_REPORT.md`, `out/client_delivery/CLIENT_TRIAL_SUMMARY.md`, `out/client_delivery/NEXT_TRIAL_PLAN.md`, and `out/client_delivery/INTERNAL_TRIAL_ANALYSIS.md` exist.
- [ ] Build the client success dashboard with `python3 scripts/build_client_success_dashboard.py`.
- [ ] Confirm `analytics/client_success_dashboard.json`, `analytics/client_trial_closeout_report.json`, `analytics/operator_closeout_checklist.json`, and `analytics/next_engagement_recommendation.json` exist.
- [ ] Confirm `out/client_delivery/CLIENT_SUCCESS_DASHBOARD.md`, `out/client_delivery/TRIAL_CLOSEOUT_REPORT.md`, `out/client_delivery/OPERATOR_CLOSEOUT_CHECKLIST.md`, and `out/client_delivery/NEXT_ENGAGEMENT_RECOMMENDATION.md` exist.
- [ ] Build the client success package dry run with `python3 scripts/package_client_success_delivery.py --dry-run`.
- [ ] Verify the client success package with `python3 scripts/verify_client_success_package.py`.
- [ ] Build the presentation overview with `python3 scripts/build_client_success_presentation.py`.
- [ ] Confirm `analytics/client_success_delivery_package.json`, `analytics/client_success_delivery_checklist.json`, `analytics/client_success_presentation_manifest.json`, and `analytics/client_success_package_verification.json` exist.
- [ ] Confirm `out/client_success_package/README_CLIENT_SUCCESS_PACKAGE.md`, `out/client_success_package/CLIENT_SUCCESS_DELIVERY_CHECKLIST.md`, and `out/client_success_package/CLIENT_PRESENTATION_OVERVIEW.md` exist.
- [ ] Confirm original media, raw clips, logs, runtime DB files, local connector config, token vault files, secrets, and credentials are excluded.
- [ ] Confirm client response notes, release notes, success reports, closeout reports, and next engagement recommendations are reviewed before sending and no cloud ticket sync or automatic client messaging is enabled.
- [ ] Confirm no cloud APIs, social APIs, or direct posting APIs are configured.

## Handoff

- [ ] Send the newest DMG from `dist/`.
- [ ] Send `out/trial_release/`.
- [ ] Include `CLIENT_QUICK_START.md`.
- [ ] Include `TRIAL_LIMITATIONS.md`.
- [ ] Ask the client to capture feedback locally with the Trial Ops feedback template.
