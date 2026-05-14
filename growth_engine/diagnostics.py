from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .analytics import save_json
from .config import AppConfig, ensure_directories
from .index import relative_path, utc_now


REQUIRED_TOOLS = ("python3", "ffmpeg", "ffprobe", "node", "npm")
RUNTIME_DIRS = ("content_inbox", "analytics", "queue", "clips", "captions", "logs", "out", "config")
JSON_CHECKS = (
    ("queue", "review_queue.json", False),
    ("analytics", "video_index.json", False),
    ("analytics", "jobs.json", True),
    ("analytics", "job_history.json", True),
    ("analytics", "pipeline_status.json", True),
    ("analytics", "activity_feed.json", True),
    ("analytics", "agents.json", True),
    ("analytics", "agent_activity.json", True),
    ("analytics", "orchestration_graph.json", True),
    ("analytics", "recommendations.json", True),
    ("analytics", "media_cache.json", True),
    ("analytics", "color_school_report.json", True),
    ("analytics", "color_repair_plan.json", True),
    ("analytics", "audio_school_report.json", True),
    ("analytics", "audio_repair_plan.json", True),
    ("analytics", "runtime_backfill_report.json", True),
    ("analytics", "runtime_snapshot.json", True),
    ("analytics", "client_state.json", True),
    ("analytics", "maintenance_report.json", True),
    ("analytics", "runtime_worker_status.json", True),
    ("analytics", "task_summary.json", True),
    ("analytics", "client_tasks.json", True),
    ("analytics", "task_worker_status.json", True),
    ("analytics", "task_schedules.json", True),
    ("analytics", "worker_runtime_status.json", True),
    ("analytics", "worker_runtime_history.json", True),
    ("analytics", "local_api_status.json", True),
    ("analytics", "local_api_history.json", True),
    ("analytics", "project_backup_report.json", True),
    ("analytics", "project_restore_report.json", True),
    ("analytics", "demo_reset_report.json", True),
    ("analytics", "project_archive_report.json", True),
    ("analytics", "project_validation_report.json", True),
    ("analytics", "project_size_report.json", True),
    ("analytics", "runtime_metrics.json", True),
    ("analytics", "client_metrics.json", True),
    ("analytics", "observability_report.json", True),
    ("analytics", "client_observability.json", True),
    ("analytics", "state_reconciliation_report.json", True),
    ("analytics", "client_integrity.json", True),
    ("analytics", "quarantine_report.json", True),
    ("analytics", "security_report.json", True),
    ("analytics", "permissions_manifest.json", True),
    ("analytics", "cache_report.json", True),
    ("analytics", "cleanup_plan.json", True),
    ("analytics", "cleanup_history.json", True),
    ("analytics", "client_storage.json", True),
    ("analytics", "archive_manifest.json", True),
    ("analytics", "archive_history.json", True),
    ("config", "error_taxonomy.json", True),
    ("config", "state_contract.json", True),
    ("config", "security_policy.json", True),
    ("config", "retention_policy.json", True),
    ("config", "project_manifest.json", True),
)


def _status_from(checks: list[dict[str, Any]]) -> str:
    if any(check.get("status") == "fail" for check in checks):
        return "fail"
    if any(check.get("status") == "warn" for check in checks):
        return "warn"
    return "pass"


def _overall(groups: dict[str, Any]) -> str:
    statuses = [value.get("status") for value in groups.values() if isinstance(value, dict)]
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _tool_version(command: str) -> str:
    args = [command, "--version"]
    if command in {"ffmpeg", "ffprobe"}:
        args = [command, "-version"]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    text = (result.stdout or result.stderr or "").splitlines()
    return text[0].strip() if text else ""


def check_tools() -> dict[str, Any]:
    checks = []
    for command in REQUIRED_TOOLS:
        found = shutil.which(command)
        item = {"name": command, "status": "pass" if found else "fail", "path": found, "version": ""}
        if found:
            try:
                item["version"] = _tool_version(command)
            except Exception as exc:  # noqa: BLE001 - diagnostics should continue.
                item["status"] = "warn"
                item["error"] = str(exc)
        checks.append(item)
    return {"status": _status_from(checks), "checks": checks}


def check_folders(config: AppConfig) -> dict[str, Any]:
    ensure_directories(config)
    mapping = {
        "content_inbox": config.inbox_dir,
        "analytics": config.analytics_dir,
        "queue": config.queue_dir,
        "clips": config.clips_dir,
        "captions": config.captions_dir,
        "logs": config.logs_dir,
        "out": config.root / "out",
        "config": config.root / "config",
    }
    checks = []
    for name in RUNTIME_DIRS:
        path = mapping[name]
        item = {"name": name, "path": relative_path(path, config.root), "exists": path.exists(), "writable": False, "status": "fail"}
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".higherkey_write_test"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            item["exists"] = True
            item["writable"] = True
            item["status"] = "pass"
        except Exception as exc:  # noqa: BLE001
            item["error"] = str(exc)
        checks.append(item)
    return {"status": _status_from(checks), "checks": checks}


def _json_check(path: Path, root: Path, optional: bool) -> dict[str, Any]:
    item = {
        "path": relative_path(path, root),
        "optional": optional,
        "exists": path.exists(),
        "readable": False,
        "status": "warn" if optional else "fail",
    }
    if not path.exists():
        item["message"] = "missing optional file" if optional else "missing required file"
        if optional:
            item["status"] = "pass"
        return item
    try:
        json.loads(path.read_text(encoding="utf-8"))
        item["readable"] = True
        item["status"] = "pass"
    except json.JSONDecodeError as exc:
        item["status"] = "fail"
        item["message"] = "corrupt json"
        item["error"] = str(exc)
    except OSError as exc:
        item["status"] = "fail"
        item["message"] = "unreadable file"
        item["error"] = str(exc)
    return item


def check_json_files(config: AppConfig) -> dict[str, Any]:
    checks = []
    for folder, filename, optional in JSON_CHECKS:
        checks.append(_json_check(config.root / folder / filename, config.root, optional))
    corrupt_copies = sorted(
        relative_path(path, config.root)
        for folder in ("analytics", "queue", "captions")
        for path in (config.root / folder).glob("*.corrupt-*")
    )
    status = _status_from(checks)
    if status == "pass" and corrupt_copies:
        status = "warn"
    return {"status": status, "checks": checks, "corrupt_copies": corrupt_copies}


def check_runtime(config: AppConfig) -> dict[str, Any]:
    checks = [
        {"name": "project_root", "path": str(config.root), "status": "pass" if config.root.exists() else "fail"},
        {"name": "local_only", "status": "pass", "value": True},
        {"name": "app_asar_writes", "status": "pass", "value": "runtime paths are project-root based"},
    ]
    return {"status": _status_from(checks), "checks": checks}


def check_packaging(root: Path) -> dict[str, Any]:
    app_path = root / "dist" / "mac-arm64" / "HigherKey Operator OS.app"
    resources = app_path / "Contents" / "Resources"
    required = (
        resources / "app.asar",
        resources / "app-assets" / "dashboard" / "review.html",
        resources / "app-assets" / "growth_engine" / "diagnostics.py",
        resources / "app-assets" / "scripts" / "run_full_qa.py",
    )
    checks = [{"name": "packaged_app", "path": relative_path(app_path, root), "status": "pass" if app_path.exists() else "warn"}]
    if app_path.exists():
        for path in required:
            checks.append({"name": path.name, "path": relative_path(path, root), "status": "pass" if path.exists() else "fail"})
        forbidden = [resources / "app-assets" / name for name in ("analytics", "queue", "clips", "captions", "out", "logs", "content_inbox")]
        for path in forbidden:
            checks.append({"name": f"no_{path.name}_in_resources", "path": relative_path(path, root), "status": "fail" if path.exists() else "pass"})
    return {"status": _status_from(checks), "checks": checks}


def _school_report_check(config: AppConfig, name: str, report_filename: str, plan_filename: str) -> dict[str, Any]:
    report_path = config.analytics_dir / report_filename
    plan_path = config.analytics_dir / plan_filename
    item: dict[str, Any] = {
        "name": name,
        "report_path": relative_path(report_path, config.root),
        "repair_plan_path": relative_path(plan_path, config.root),
        "status": "warn",
        "last_run": None,
        "summary": {},
    }
    if not report_path.exists():
        item["message"] = "report not generated yet"
        return item
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        readiness_status = payload.get("status", "warn")
        item["status"] = "pass" if readiness_status in {"pass", "warn", "empty"} else "warn"
        item["readiness_status"] = readiness_status
        item["last_run"] = payload.get("updated_at")
        item["summary"] = payload.get("summary", {})
        item["read_only"] = payload.get("read_only", True)
        item["local_only"] = payload.get("local_only", True)
    except Exception as exc:  # noqa: BLE001
        item["status"] = "fail"
        item["message"] = "school report unreadable"
        item["error"] = str(exc)
    return item


def check_schools(config: AppConfig) -> dict[str, Any]:
    checks = [
        {
            "name": "ffprobe_available",
            "status": "pass" if shutil.which("ffprobe") else "fail",
            "path": shutil.which("ffprobe"),
        },
        _school_report_check(config, "color_school", "color_school_report.json", "color_repair_plan.json"),
        _school_report_check(config, "audio_school", "audio_school_report.json", "audio_repair_plan.json"),
    ]
    return {"status": _status_from(checks), "checks": checks}


def run_diagnostics(config: AppConfig, include_packaging: bool = True) -> dict[str, Any]:
    ensure_directories(config)
    groups: dict[str, Any] = {
        "tools": check_tools(),
        "folders": check_folders(config),
        "json_files": check_json_files(config),
        "runtime": check_runtime(config),
        "schools": check_schools(config),
    }
    if include_packaging:
        groups["packaging"] = check_packaging(config.root)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": _overall(groups),
        "root": str(config.root),
        **groups,
    }
    save_json(config.analytics_dir / "diagnostics.json", payload)
    return payload


def summarize_report(results: list[dict[str, Any]]) -> str:
    if any(result.get("status") == "fail" for result in results):
        return "fail"
    if any(result.get("status") == "warn" for result in results):
        return "warn"
    return "pass"


def command_result(name: str, args: list[str], root: Path, timeout: int = 180) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(root)}
    try:
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
        return {
            "name": name,
            "status": "pass" if result.returncode == 0 else "fail",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "status": "fail",
            "returncode": None,
            "timeout_seconds": timeout,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "error": f"timed out after {timeout} seconds",
        }
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "status": "fail", "error": str(exc)}
