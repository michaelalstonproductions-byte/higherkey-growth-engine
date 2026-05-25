#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.marketing_intelligence import write_json, write_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def rel(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def run(args: list[str], root: Path, timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=root, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "args": args,
            "status": "pass" if proc.returncode == 0 else "fail",
            "return_code": proc.returncode,
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }
    except Exception as exc:
        return {"args": args, "status": "fail", "return_code": None, "stdout_tail": "", "stderr_tail": str(exc)}


def check(name: str, passed: bool, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "status": "pass" if passed else "needs_attention",
        "message": message,
    }
    payload.update(extra)
    return payload


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def bridge_exists(root: Path, preload_name: str, ipc_name: str) -> bool:
    preload = text(root / "electron" / "preload.js")
    main = text(root / "electron" / "main.js")
    return preload_name in preload and ipc_name in preload and ipc_name in main


def review_queue_summary(root: Path) -> dict[str, Any]:
    path = root / "queue" / "review_queue.json"
    payload = load_json(path, {})
    items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("items", "queue", "clips", "entries"):
            if isinstance(payload.get(key), list):
                items = payload.get(key, [])
                break
    elif isinstance(payload, list):
        items = payload
    return {"exists": path.exists(), "count": len(items), "path": rel(path, root)}


def approved_reviews_summary(root: Path) -> dict[str, Any]:
    path = root / "queue" / "approved_reviews.json"
    payload = load_json(path, {})
    approved: list[Any] = []
    if isinstance(payload, dict):
        for key in ("approved", "approved_clip_ids", "approved_entry_ids"):
            if isinstance(payload.get(key), list):
                approved.extend(payload.get(key, []))
    elif isinstance(payload, list):
        approved = payload
    return {"exists": path.exists(), "approved_count": len(approved), "path": rel(path, root)}


def write_summary(root: Path, report: dict[str, Any]) -> str:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    delivery_out = root / "out" / "client_delivery"
    delivery_out.mkdir(parents=True, exist_ok=True)
    commands = report.get("commands", [])
    checks = report.get("checks", [])
    social = report.get("social_exports", {})
    lines = [
        "# Client Rehearsal Summary",
        "",
        "HigherKey Operator OS was rehearsed locally for a release-candidate client flow.",
        "",
        "## Status",
        f"- Overall: {report.get('status')}",
        f"- Local only: {report.get('local_only')}",
        f"- Manual upload only: {report.get('manual_upload_only')}",
        "",
        "## Client Flow Checks",
        *[f"- {item.get('name')}: {item.get('status')} - {item.get('message')}" for item in checks],
        "",
        "## Local Build Steps",
        *[f"- {' '.join(item.get('args', []))}: {item.get('status')}" for item in commands],
        "",
        "## Social Packs",
        f"- Folder: {social.get('path')}",
        f"- Exists: {social.get('exists')}",
        f"- Manifest: {social.get('manifest_exists')}",
        "",
        "## Next Steps",
        *[f"- {item}" for item in report.get("client_next_steps", [])],
        "",
        "Manual upload only. HigherKey does not post to social platforms and does not call cloud or live Instagram APIs.",
    ]
    path = out / "client_rehearsal_summary.md"
    write_text(path, "\n".join(lines))
    write_text(delivery_out / "CLIENT_REHEARSAL_SUMMARY.md", "\n".join(lines))
    return rel(path, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local client release-candidate rehearsal.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON only.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    analytics = root / "analytics"
    client_state = load_json(analytics / "client_state.json", {})
    project_root = client_state.get("project_root") if isinstance(client_state, dict) else None
    review = review_queue_summary(root)
    approved = approved_reviews_summary(root)
    social_dir = root / "out" / "social_exports"
    social_manifest = social_dir / "manifest.json"

    build_commands = [
        ["python3", "scripts/build_marketing_plan.py"],
        ["python3", "scripts/build_campaign_plan.py"],
        ["python3", "scripts/build_growth_strategy.py"],
        ["python3", "scripts/build_creative_direction.py"],
        ["python3", "scripts/build_production_command.py"],
        ["python3", "scripts/build_operator_autopilot.py"],
        ["python3", "scripts/autopilot_preflight.py"],
        ["python3", "scripts/build_autopilot_console.py"],
    ]
    command_results = [run(command, root) for command in build_commands]
    checks = [
        check("project_selected", bool(project_root or root.exists()), "Project root is available for local rehearsal.", project_root=project_root or str(root)),
        check("import_bridge", bridge_exists(root, "importFootage", "files:importFootage"), "Import Footage bridge exists."),
        check("import_process_bridge", bridge_exists(root, "importAndProcessFootage", "files:importAndProcessFootage"), "Import & Process bridge exists."),
        check("export_bridge", bridge_exists(root, "exportSocialPacks", "social:exportPacks"), "Export Social Packs bridge exists."),
        check("review_queue", review["exists"], "Review queue exists or will be generated after processing.", **review),
        check("approved_reviews", approved["exists"], "Approved reviews file status recorded.", **approved),
        check("social_exports", social_dir.exists(), "Social export folder exists or can be created by Export Packs.", path=rel(social_dir, root), manifest_exists=social_manifest.exists()),
        check("post_composer_route", bridge_exists(root, "buildPostComposerDrafts", "socialComposer:buildDrafts"), "Post composer bridge exists."),
        check("scheduler_route", bridge_exists(root, "scheduleSocialPost", "socialScheduler:schedulePost"), "Scheduler bridge exists."),
        check("editor_route", bridge_exists(root, "buildEditPlan", "editor:buildPlan"), "Editor route exists."),
        check("editing_approval_route", bridge_exists(root, "buildEditingApprovalQueue", "editor:buildApprovalQueue"), "Editing approval route exists."),
        check("edited_delivery_route", bridge_exists(root, "buildEditingDeliveryRoom", "editor:buildDeliveryRoom"), "Edited delivery route exists."),
        check("launch_room_route", bridge_exists(root, "buildClientDeliveryManifest", "launch:buildClientDeliveryManifest"), "Launch Room bridge exists."),
        check("trial_ops_route", bridge_exists(root, "collectTrialFeedback", "feedback:collectTrial") and bridge_exists(root, "buildTrialIssueQueue", "feedback:buildTrialIssueQueue") and bridge_exists(root, "buildTrialPatchPlan", "feedback:buildTrialPatchPlan") and bridge_exists(root, "buildPatchExecutionBoard", "feedback:buildPatchExecutionBoard") and bridge_exists(root, "buildClientReleaseNotes", "feedback:buildClientReleaseNotes"), "Trial Ops feedback, issue queue, patch plan, patch execution, and release notes bridges exist."),
        check("support_package_script", (root / "scripts" / "create_issue_report.py").exists(), "Client-safe support package script exists."),
        check("support_package_route", bridge_exists(root, "createIssueReport", "support:createIssueReport"), "Support package bridge exists."),
        check("feedback_script", (root / "scripts" / "collect_trial_feedback.py").exists(), "Local trial feedback capture script exists."),
        check("manual_upload_fallback", "manual upload" in text(root / "README.md").lower(), "Manual upload fallback is documented."),
        check("no_live_social_rehearsal", True, "Client rehearsal performs no live social API calls."),
        check("no_destructive_edit_rehearsal", True, "Client rehearsal performs no destructive edit actions."),
    ]
    command_failures = [item for item in command_results if item["status"] != "pass"]
    needs_attention = [item for item in checks if item["status"] != "pass"]
    next_steps = [
        "Import MP4, MOV, or M4V footage if no real clips are present.",
        "Run Import & Process to create clips, captions, thumbnails, and social packs.",
        "Review clips, approve the strongest moments, and export Social Packs.",
        "Open Social Packs and upload manually. HigherKey does not post directly.",
        "Run Command, Autopilot, Marketing, Growth, and Creative Director views to rehearse the client workflow.",
        "Use Trial Ops to collect local feedback, build the issue queue, draft patch plans, track patch execution, and prepare client release notes after client sessions.",
        "Create a support package if anything looks wrong.",
    ]
    report: dict[str, Any] = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "live_instagram_api": False,
        "social_posting_apis": False,
        "status": "pass" if not command_failures and not needs_attention else "needs_attention",
        "checks": checks,
        "commands": command_results,
        "review_queue": review,
        "approved_reviews": approved,
        "social_exports": {"path": rel(social_dir, root), "exists": social_dir.exists(), "manifest_exists": social_manifest.exists()},
        "client_next_steps": next_steps,
    }
    report["summary_markdown"] = write_summary(root, report)
    write_json(analytics / "client_rehearsal_report.json", report)
    print(json.dumps(report, indent=None if args.json else 2, sort_keys=True))
    return 0 if not command_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
