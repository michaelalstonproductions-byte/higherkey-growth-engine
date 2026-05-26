#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def latest_dmg_name(package_version: str) -> str:
    return f"HigherKey Operator OS-{package_version}-arm64.dmg"


def write_text(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def feedback_template() -> dict[str, object]:
    return {
        "client_name": "",
        "session_date": "",
        "what_worked": "",
        "what_confused_you": "",
        "bugs_seen": "",
        "feature_requests": "",
        "upload_workflow_rating": None,
        "overall_rating": None,
        "notes": "",
        "local_only": True,
    }


def package_trial(root: Path, output: Path, dry_run: bool = False, include_dmg: bool = False) -> dict[str, object]:
    package = load_json(root / "package.json", {})
    release = load_json(root / "config" / "release.json", {})
    package_version = str(package.get("version") or "4.7.0")
    release_version = str(release.get("version") or "V4.7")
    dmg_path = root / "dist" / latest_dmg_name(package_version)
    output = output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()

    docs = {
        "CLIENT_HANDOFF_GUIDE.md": root / "CLIENT_HANDOFF_GUIDE.md",
        "CLIENT_QUICK_START.md": root / "CLIENT_QUICK_START.md",
        "BETA_READINESS_CHECKLIST.md": root / "BETA_READINESS_CHECKLIST.md",
        "DEMO_CHECKLIST.md": root / "DEMO_CHECKLIST.md",
        "RELEASE_NOTES.md": root / "RELEASE_NOTES.md",
        "TRIAL_LIMITATIONS.md": root / "TRIAL_LIMITATIONS.md",
        "TRIAL_DELIVERY_CHECKLIST.md": root / "TRIAL_DELIVERY_CHECKLIST.md",
        "CLIENT_TRIAL_QA_SUMMARY.md": root / "CLIENT_TRIAL_QA_SUMMARY.md",
        "CLIENT_DELIVERY_README.md": root / "out" / "client_delivery" / "CLIENT_DELIVERY_README.md",
        "CLIENT_DELIVERY_CHECKLIST.md": root / "out" / "client_delivery" / "CLIENT_DELIVERY_CHECKLIST.md",
        "TRIAL_ISSUE_QUEUE.md": root / "out" / "client_delivery" / "TRIAL_ISSUE_QUEUE.md",
        "TRIAL_FIX_PLAN.md": root / "out" / "client_delivery" / "TRIAL_FIX_PLAN.md",
        "TRIAL_PATCH_PLAN.md": root / "out" / "client_delivery" / "TRIAL_PATCH_PLAN.md",
        "CLIENT_RESPONSE_NOTES.md": root / "out" / "client_delivery" / "CLIENT_RESPONSE_NOTES.md",
        "TRIAL_RISK_SUMMARY.md": root / "out" / "client_delivery" / "TRIAL_RISK_SUMMARY.md",
        "PATCH_EXECUTION_BOARD.md": root / "out" / "client_delivery" / "PATCH_EXECUTION_BOARD.md",
        "PATCH_VERIFICATION_CHECKLIST.md": root / "out" / "client_delivery" / "PATCH_VERIFICATION_CHECKLIST.md",
        "CLIENT_RELEASE_NOTES.md": root / "out" / "client_delivery" / "CLIENT_RELEASE_NOTES.md",
        "CLIENT_UPDATE_MESSAGE.md": root / "out" / "client_delivery" / "CLIENT_UPDATE_MESSAGE.md",
        "TRIAL_SUCCESS_REPORT.md": root / "out" / "client_delivery" / "TRIAL_SUCCESS_REPORT.md",
        "CLIENT_TRIAL_SUMMARY.md": root / "out" / "client_delivery" / "CLIENT_TRIAL_SUMMARY.md",
        "NEXT_TRIAL_PLAN.md": root / "out" / "client_delivery" / "NEXT_TRIAL_PLAN.md",
        "CLIENT_SUCCESS_DASHBOARD.md": root / "out" / "client_delivery" / "CLIENT_SUCCESS_DASHBOARD.md",
        "TRIAL_CLOSEOUT_REPORT.md": root / "out" / "client_delivery" / "TRIAL_CLOSEOUT_REPORT.md",
        "OPERATOR_CLOSEOUT_CHECKLIST.md": root / "out" / "client_delivery" / "OPERATOR_CLOSEOUT_CHECKLIST.md",
        "NEXT_ENGAGEMENT_RECOMMENDATION.md": root / "out" / "client_delivery" / "NEXT_ENGAGEMENT_RECOMMENDATION.md",
    }
    missing_docs = [name for name, source in docs.items() if not source.exists()]
    app_info = {
        "product": "HigherKey Operator OS",
        "package_version": package_version,
        "release_version": release_version,
        "release_name": release.get("release_name", "Client Trial Package"),
        "created_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "social_apis": False,
        "direct_posting_apis": False,
    }
    pointer = {
        "expected_dmg": str(dmg_path.relative_to(root)),
        "exists": dmg_path.exists(),
        "copied": bool(include_dmg and dmg_path.exists()),
        "package_version": package_version,
        "release_version": release_version,
        "note": "The trial package points to the newest local DMG. It only copies the DMG when --include-dmg is used.",
    }
    quick_start = "\n".join(
        [
            "HigherKey Operator OS Trial Quick Start",
            "1. Open the newest DMG from dist/.",
            "2. Launch HigherKey Operator OS.",
            "3. Click Import Footage and choose MP4, MOV, or M4V files.",
            "4. Click Import & Process.",
            "5. Review and approve the best clips.",
            "6. Export Social Packs.",
            "7. Use Editor, Editing Approval, and Edited Delivery Room for approved edited assets.",
            "8. Use Scheduler and official connector checks only when configured.",
            "9. Upload the prepared files manually unless official live posting gates are connected and approved.",
            "",
            "No cloud editing APIs, scraping, password login, or unauthorized social posting APIs are configured.",
            "",
        ]
    )
    support_note = "\n".join(
        [
            "HigherKey Operator OS Trial Support",
            "",
            "Use Create Support Package inside the app if something fails.",
            "The support package excludes original footage, private generated media, full logs, runtime DB files, and local tokens by default.",
            "Trial packages exclude content_inbox, clips, captions, logs, runtime DB files, local connector config, live publish policy, tokens, secrets, and credentials.",
            "Unsigned local DMGs may require macOS approval before opening.",
            "",
            "Local command:",
            "python3 scripts/create_issue_report.py",
            "python3 scripts/collect_trial_feedback.py --template",
            "python3 scripts/build_trial_issue_queue.py",
            "python3 scripts/build_trial_patch_plan.py",
            "python3 scripts/build_patch_execution_board.py",
            "python3 scripts/build_client_release_notes.py",
            "python3 scripts/build_trial_success_report.py",
            "python3 scripts/build_client_success_dashboard.py",
            "",
        ]
    )
    trial_limitations = docs["TRIAL_LIMITATIONS.md"].read_text(encoding="utf-8") if docs["TRIAL_LIMITATIONS.md"].exists() else "Local-first trial. Manual upload only. No cloud or social APIs.\n"

    included = [name for name, source in docs.items() if source.exists()]
    generated = [
        "app_info.json",
        "latest_dmg_pointer.json",
        "quick_start.txt",
        "support_note.txt",
        "trial_limitations.txt",
        "client_feedback_template.json",
    ]
    if include_dmg and dmg_path.exists():
        included.append(dmg_path.name)

    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
        for name, source in docs.items():
            if source.exists():
                shutil.copy2(source, output / name)
        write_text(output / "quick_start.txt", quick_start)
        write_text(output / "support_note.txt", support_note)
        write_text(output / "trial_limitations.txt", trial_limitations)
        (output / "app_info.json").write_text(json.dumps(app_info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "latest_dmg_pointer.json").write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "client_feedback_template.json").write_text(json.dumps(feedback_template(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if include_dmg and dmg_path.exists():
            shutil.copy2(dmg_path, output / dmg_path.name)

    status = "pass" if not missing_docs else "warn"
    return {
        "status": status,
        "dry_run": dry_run,
        "local_only": True,
        "manual_upload_only": True,
        "private_media_copied": False,
        "runtime_media_copied": False,
        "include_dmg": include_dmg,
        "output": str(output),
        "included": included + generated,
        "missing_docs": missing_docs,
        "latest_dmg_pointer": pointer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a client trial release package without private footage or runtime media.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--output", default="out/trial_release", help="Output folder.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing files.")
    parser.add_argument("--include-dmg", action="store_true", help="Copy the latest local DMG into the trial package.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = package_trial(root, Path(args.output), dry_run=args.dry_run, include_dmg=args.include_dmg)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
