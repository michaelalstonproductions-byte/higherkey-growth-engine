# HigherKey Operator OS Trial Delivery Checklist

Use this checklist before handing a trial build to a client.

## V7.0 Client Delivery

- [ ] Run Launch Room > Run Launch Audit.
- [ ] Run Launch Room > Run Client Rehearsal.
- [ ] Build the client delivery manifest.
- [ ] Build or dry-run client handoff.
- [ ] Build or dry-run trial package.
- [ ] Verify edited delivery package when edited assets are included.
- [ ] Confirm manual upload fallback is visible.
- [ ] Confirm optional social connection language does not imply automatic posting.
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
- [ ] Confirm no cloud APIs, social APIs, or direct posting APIs are configured.

## Handoff

- [ ] Send the newest DMG from `dist/`.
- [ ] Send `out/trial_release/`.
- [ ] Include `CLIENT_QUICK_START.md`.
- [ ] Include `TRIAL_LIMITATIONS.md`.
- [ ] Ask the client to capture feedback locally with the in-app feedback action.
