#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.runtime_lock import acquire_lock, release_lock
from growth_engine.task_queue import claim_next_task, complete_task, fail_task, get_task, task_summary, update_task_progress
from growth_engine.worker_runtime import heartbeat, read_status, start_session, stop_session


TASK_COMMANDS = {
    "repair_project_media": ["python3", "scripts/repair_project_media.py"],
    "run_pipeline": ["python3", "scripts/run_pipeline.py"],
    "rebuild_metadata_index": ["python3", "scripts/rebuild_metadata_index.py"],
    "build_media_cache": ["python3", "scripts/build_media_cache.py"],
    "run_orchestrator": ["python3", "scripts/run_orchestrator.py", "--once"],
    "run_color_school": ["python3", "scripts/run_color_school.py"],
    "run_audio_school": ["python3", "scripts/run_audio_school.py"],
    "build_runtime_snapshot": ["python3", "scripts/build_runtime_snapshot.py"],
    "export_approved_posts": ["python3", "scripts/export_approved_posts.py"],
    "export_social_packs": ["python3", "scripts/export_social_packs.py"],
    "run_diagnostics": ["python3", "scripts/run_diagnostics.py"],
    "run_full_qa": ["python3", "scripts/run_full_qa.py", "--skip-smoke"],
    "maintenance": ["python3", "scripts/run_maintenance.py"],
    "backup_project": ["python3", "scripts/backup_project.py"],
    "restore_project": ["python3", "scripts/restore_project.py"],
    "reset_demo_workspace": ["python3", "scripts/reset_demo_workspace.py", "--soft"],
    "archive_project_artifacts": ["python3", "scripts/archive_project_artifacts.py"],
    "validate_project": ["python3", "scripts/validate_project.py"],
    "project_size_report": ["python3", "scripts/project_size_report.py"],
    "storage_report": ["python3", "scripts/manage_storage.py", "report"],
    "cleanup_plan": ["python3", "scripts/manage_storage.py", "plan", "--dry-run"],
    "cleanup_apply": ["python3", "scripts/manage_storage.py", "apply"],
    "archive_generated_artifacts": ["python3", "scripts/manage_storage.py", "archive"],
    "vacuum_runtime_db": ["python3", "scripts/manage_storage.py", "vacuum-db"],
}
HEAVY_TASKS = {"build_media_cache", "run_color_school", "run_audio_school", "run_full_qa", "maintenance", "export_social_packs", "backup_project", "restore_project", "reset_demo_workspace", "archive_project_artifacts", "cleanup_apply", "archive_generated_artifacts", "vacuum_runtime_db"}


def append_history(root: Path, entry: dict[str, Any]) -> None:
    path = root / "analytics" / "task_worker_history.json"
    history = load_json_file(path, {"version": 1, "runs": []})
    history.setdefault("runs", []).append(entry)
    history["runs"] = history["runs"][-200:]
    history["updated_at"] = utc_now()
    save_json_file(path, history)


def _payload_args(task: dict[str, Any]) -> list[str]:
    payload = task.get("payload") or {}
    args: list[str] = []
    if task["task_type"] == "build_media_cache" and payload.get("limit"):
        args.extend(["--limit", str(payload["limit"])])
    if task["task_type"] in {"run_color_school", "run_audio_school"} and payload.get("quick"):
        args.append("--quick")
    if task["task_type"] == "export_social_packs":
        for platform in payload.get("platforms", []) or []:
            args.extend(["--platform", platform])
        for approved_id in payload.get("approved_ids", []) or []:
            args.extend(["--approved-id", approved_id])
    if task["task_type"] == "backup_project":
        if payload.get("include_source_media"):
            args.append("--include-source-media")
        if payload.get("include_cache"):
            args.append("--include-cache")
    if task["task_type"] == "restore_project" and payload.get("backup_path"):
        args.append(str(payload["backup_path"]))
        if payload.get("target"):
            args.extend(["--target", str(payload["target"])])
        if payload.get("force"):
            args.append("--force")
    if task["task_type"] == "reset_demo_workspace":
        args[:] = [arg for arg in args if arg != "--soft"]
        args.append("--hard" if payload.get("hard") else "--soft")
        if payload.get("archive_first"):
            args.append("--archive-first")
        if payload.get("confirm_delete_source_media"):
            args.append("--confirm-delete-source-media")
    if task["task_type"] in {"cleanup_apply", "archive_generated_artifacts", "vacuum_runtime_db"}:
        if payload.get("apply"):
            args.append("--apply")
        if payload.get("confirm"):
            args.append("--confirm")
        if payload.get("category"):
            args.extend(["--category", str(payload["category"])])
    if task["task_type"] == "cleanup_plan":
        if payload.get("category"):
            args.extend(["--category", str(payload["category"])])
        if payload.get("max_age_days"):
            args.extend(["--max-age-days", str(payload["max_age_days"])])
        if payload.get("max_size_mb"):
            args.extend(["--max-size-mb", str(payload["max_size_mb"])])
    return args


def run_claimed_task(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    config = load_config(root)
    command = [*TASK_COMMANDS[task["task_type"]], *_payload_args(task)]
    env = {**os.environ, "PYTHONPATH": str(root)}
    lock = None
    started = utc_now()
    try:
        heartbeat(config, state="running", current_task_id=task["task_id"])
        update_task_progress(
            config,
            task["task_id"],
            progress_percent=10,
            current_stage=task["task_type"],
            stage_message=f"Running {task['task_type']}",
            client_message=client_message_for(task["task_type"], "running"),
        )
        if get_task(config, task["task_id"]) and get_task(config, task["task_id"]).get("cancellation_requested"):
            payload = {"task_id": task["task_id"], "task_type": task["task_type"], "status": "cancelled", "client_message": "Task cancelled before it started.", "retryable": False}
            fail_task(config, task["task_id"], payload)
            return payload
        if task["task_type"] in HEAVY_TASKS:
            lock = acquire_lock(config, f"task:{task['task_type']}", force=False)
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
        parsed = parse_json(result.stdout)
        warning_count = len(parsed.get("warnings", [])) if isinstance(parsed.get("warnings"), list) else int(parsed.get("warning_count", 0) or 0)
        skipped_count = int(parsed.get("skipped", parsed.get("skipped_count", 0)) or 0)
        severity = str(parsed.get("severity") or parsed.get("status") or "").lower()
        client_message = client_message_for(task["task_type"], "completed")
        if severity in {"warn", "needs_attention"}:
            client_message = "Needs attention: older missing media skipped" if task["task_type"] == "run_pipeline" else "Completed with warnings."
        payload = {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "command": command,
            "returncode": result.returncode,
            "started_at": started,
            "completed_at": utc_now(),
            "warning_count": warning_count,
            "skipped_count": skipped_count,
            "client_message": client_message,
            "output_summary": safe_output_summary(parsed),
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
        if result.returncode == 0:
            update_task_progress(
                config,
                task["task_id"],
                progress_percent=95,
                current_stage="finalizing",
                stage_message="Finalizing task output",
                client_message=client_message,
                warning_count=warning_count,
                skipped_count=skipped_count,
                output_summary=safe_output_summary(parsed),
            )
            complete_task(config, task["task_id"], payload)
            payload["status"] = "completed"
        else:
            fail_task(config, task["task_id"], payload)
            payload["status"] = "failed"
        return payload
    except Exception as exc:  # noqa: BLE001
        payload = {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "status": "failed",
            "error": str(exc),
            "client_message": "Needs attention. See diagnostics for details.",
            "retryable": True,
            "started_at": started,
            "completed_at": utc_now(),
        }
        fail_task(config, task["task_id"], payload)
        return payload
    finally:
        if lock:
            release_lock(config)


def run_worker(root: Path, *, once: bool, interval: float, max_tasks: int, task_type: str | None, dry_run: bool) -> dict[str, Any]:
    config = load_config(root)
    processed: list[dict[str, Any]] = []
    if dry_run:
        summary = task_summary(config)
        report = {"version": 1, "updated_at": utc_now(), "status": "pass", "dry_run": True, "summary": summary, "processed": []}
        save_json_file(config.analytics_dir / "task_worker_status.json", report)
        return report
    start_session(config, pid=os.getpid(), command="scripts/run_task_worker.py", state="starting")
    while True:
        worker_status = read_status(config)
        if worker_status.get("stop_requested"):
            break
        if worker_status.get("pause_requested"):
            heartbeat(config, state="paused")
            if once:
                break
            time.sleep(interval)
            continue
        if len(processed) >= max_tasks:
            break
        task = claim_next_task(config, task_type=task_type)
        if not task:
            heartbeat(config, state="idle", current_task_id=None)
            if once:
                break
            time.sleep(interval)
            continue
        processed.append(run_claimed_task(config.root, task))
        if once:
            break
        time.sleep(interval)
    status = "fail" if any(item.get("status") == "failed" for item in processed) else "pass"
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "dry_run": False,
        "processed": processed,
        "summary": task_summary(config),
        "local_only": True,
    }
    save_json_file(config.analytics_dir / "task_worker_status.json", report)
    append_history(config.root, report)
    stop_session(config, reason="worker cycle complete")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey durable task worker.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--once", action="store_true", help="Process at most one task.")
    parser.add_argument("--interval", type=float, default=10.0, help="Polling interval when processing more than one task.")
    parser.add_argument("--max-tasks", type=int, default=1, help="Maximum tasks to process.")
    parser.add_argument("--task-type", default=None, help="Only claim a specific task type.")
    parser.add_argument("--dry-run", action="store_true", help="Report task summary without claiming or running tasks.")
    args = parser.parse_args()
    report = run_worker(Path(args.root).resolve(), once=args.once, interval=args.interval, max_tasks=args.max_tasks, task_type=args.task_type, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


def parse_json(value: str) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def safe_output_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"stdout", "stderr", "stdout_tail", "stderr_tail"}
    }


def client_message_for(task_type: str, state: str) -> str:
    if state == "completed":
        return {
            "repair_project_media": "Project media checked.",
            "run_pipeline": "Ready for review.",
            "rebuild_metadata_index": "Metadata indexed.",
            "build_media_cache": "Thumbnails ready.",
            "run_color_school": "Color analysis complete.",
            "run_audio_school": "Audio analysis complete.",
            "run_orchestrator": "Agents updated.",
            "build_runtime_snapshot": "Runtime state updated.",
            "export_social_packs": "Social exports prepared.",
            "maintenance": "Maintenance complete.",
            "backup_project": "Project backup complete.",
            "restore_project": "Project restore complete.",
            "reset_demo_workspace": "Demo workspace reset complete.",
            "archive_project_artifacts": "Project artifacts archived.",
            "validate_project": "Project validation complete.",
            "project_size_report": "Project size report complete.",
            "storage_report": "Storage report complete.",
            "cleanup_plan": "Cleanup plan ready.",
            "cleanup_apply": "Cleanup complete.",
            "archive_generated_artifacts": "Generated artifacts archived.",
            "vacuum_runtime_db": "Runtime database vacuum complete.",
        }.get(task_type, "Task complete.")
    return {
        "repair_project_media": "Checking media references",
        "run_pipeline": "Creating clips",
        "rebuild_metadata_index": "Indexing metadata",
        "build_media_cache": "Building thumbnails",
        "run_color_school": "Analyzing color",
        "run_audio_school": "Analyzing audio",
        "run_orchestrator": "Updating agents",
        "build_runtime_snapshot": "Updating runtime state",
        "export_social_packs": "Preparing social exports",
        "maintenance": "Running maintenance",
        "backup_project": "Backing up project",
        "restore_project": "Restoring project",
        "reset_demo_workspace": "Resetting demo workspace",
        "archive_project_artifacts": "Archiving project artifacts",
        "validate_project": "Validating project",
        "project_size_report": "Building project size report",
        "storage_report": "Measuring local storage",
        "cleanup_plan": "Building cleanup plan",
        "cleanup_apply": "Applying confirmed cleanup",
        "archive_generated_artifacts": "Archiving generated artifacts",
        "vacuum_runtime_db": "Vacuuming runtime database",
    }.get(task_type, "Processing task")


if __name__ == "__main__":
    raise SystemExit(main())
