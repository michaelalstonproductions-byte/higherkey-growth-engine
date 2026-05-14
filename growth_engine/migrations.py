from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig, ensure_directories
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .runtime_db import connect, init_db, migrate
from .security import validate_project_root


def load_version_contract(config: AppConfig) -> dict[str, Any]:
    return load_json_file(config.root / "config" / "version_contract.json", {})


def detect_project_version(config: AppConfig) -> str:
    release = load_json_file(config.root / "config" / "release.json", {})
    manifest = load_json_file(config.root / "config" / "project_manifest.json", {})
    return str(release.get("version") or manifest.get("version") or "unknown")


def detect_runtime_db_schema(config: AppConfig) -> int:
    try:
        with connect(config) as connection:
            migrate(connection)
            row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        return int(row["version"] or 0)
    except Exception:
        return 0


def _db_tables(config: AppConfig) -> set[str]:
    try:
        with connect(config) as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row["name"]) for row in rows}
    except Exception:
        return set()


def required_migrations(config: AppConfig) -> list[dict[str, Any]]:
    contract = load_version_contract(config)
    migrations: list[dict[str, Any]] = []
    project_check = validate_project_root(config, config.root)
    if not project_check["ok"]:
        migrations.append({"id": "project_root_invalid", "safe": False, "message": project_check["message"]})
    schema = detect_runtime_db_schema(config)
    required_schema = int(contract.get("schema_version", 0) or 0)
    if schema < required_schema:
        migrations.append({"id": "runtime_db_schema", "safe": True, "message": f"Upgrade runtime DB schema from {schema} to {required_schema}."})
    existing_tables = _db_tables(config)
    for table in contract.get("required_db_tables", []):
        if table not in existing_tables:
            migrations.append({"id": f"missing_table:{table}", "safe": True, "message": f"Create or migrate missing table {table}."})
    for rel in contract.get("required_config_files", []):
        if not (config.root / rel).exists():
            migrations.append({"id": f"missing_config:{rel}", "safe": False, "message": f"Required config file is missing: {rel}."})
    for rel in contract.get("required_runtime_files", []):
        if not (config.root / rel).exists():
            migrations.append({"id": f"missing_runtime:{rel}", "safe": True, "message": f"Runtime snapshot should be rebuilt: {rel}."})
    return migrations


def pre_upgrade_backup_manifest(config: AppConfig) -> dict[str, Any]:
    manifest = {
        "version": 1,
        "created_at": utc_now(),
        "local_only": True,
        "project_root": str(config.root),
        "recommended_command": "python3 scripts/backup_project.py --include-cache",
        "source_media_preserved": True,
        "runtime_files": [
            "analytics/runtime_state.db",
            "analytics/events.jsonl",
            "analytics/audit_log.jsonl",
            "config/project_manifest.json",
        ],
    }
    save_json_file(config.analytics_dir / "pre_upgrade_backup_manifest.json", manifest)
    return manifest


def rollback_plan(config: AppConfig, plan: dict[str, Any], *, applied: bool = False) -> dict[str, Any]:
    rollback = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "reversible": True,
        "applied": applied,
        "client_message": "Use the pre-upgrade backup reference to restore project state if needed.",
        "backup_reference": "analytics/pre_upgrade_backup_manifest.json",
        "files_changed": [
            "analytics/upgrade_plan.json",
            "analytics/upgrade_report.json",
            "analytics/client_upgrade_status.json",
            "analytics/rollback_plan.json",
        ],
        "db_migrations_applied": [item["id"] for item in plan.get("migrations", []) if item.get("safe")],
        "config_files_updated": [],
        "source_media_preserved": True,
    }
    save_json_file(config.analytics_dir / "rollback_plan.json", rollback)
    return rollback


def build_upgrade_plan(config: AppConfig) -> dict[str, Any]:
    ensure_directories(config)
    contract = load_version_contract(config)
    migrations = required_migrations(config)
    status = "fail" if any(not item.get("safe") for item in migrations) else ("warn" if migrations else "pass")
    plan = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": status,
        "current_project_version": detect_project_version(config),
        "target_app_version": contract.get("app_version", "unknown"),
        "target_release_version": contract.get("release_version", "unknown"),
        "runtime_db_schema": detect_runtime_db_schema(config),
        "required_schema": contract.get("schema_version"),
        "migrations": migrations,
        "source_media_preserved": True,
        "json_compatibility_preserved": True,
    }
    save_json_file(config.analytics_dir / "upgrade_plan.json", plan)
    rollback_plan(config, plan, applied=False)
    return plan


def _run_safe_script(config: AppConfig, script: str, *args: str) -> dict[str, Any]:
    result = subprocess.run(["python3", script, *args], cwd=config.root, capture_output=True, text=True, timeout=180, check=False)
    return {
        "script": script,
        "returncode": result.returncode,
        "status": "pass" if result.returncode == 0 else "fail",
        "stdout_tail": result.stdout[-1000:],
        "stderr_tail": result.stderr[-1000:],
    }


def apply_upgrade(config: AppConfig, *, force: bool = False) -> dict[str, Any]:
    plan = build_upgrade_plan(config)
    if plan["status"] == "fail" and not force:
        report = _upgrade_report(config, plan, "fail", applied=False, message="Upgrade has unsafe blockers. Use --force only after reviewing diagnostics.")
        return report
    backup = pre_upgrade_backup_manifest(config)
    init_db(config)
    steps = [
        _run_safe_script(config, "scripts/backfill_runtime_db.py", "--quick"),
        _run_safe_script(config, "scripts/build_task_snapshot.py"),
        _run_safe_script(config, "scripts/manage_storage.py", "report"),
        _run_safe_script(config, "scripts/reconcile_runtime_state.py", "--dry-run", "--limit", "100"),
        _run_safe_script(config, "scripts/build_runtime_snapshot.py"),
    ]
    status = "fail" if any(step["status"] == "fail" for step in steps) else "pass"
    report = _upgrade_report(config, plan, status, applied=True, message="Upgrade applied." if status == "pass" else "Upgrade needs attention.", steps=steps, backup=backup)
    rollback_plan(config, plan, applied=True)
    append_event(config, "upgrade.completed" if status == "pass" else "upgrade.failed", severity=status, source="migrations", summary={"status": status})
    write_audit_event(config, "maintenance.run", severity=status, source="migrations", summary={"action": "upgrade_apply", "status": status})
    return report


def _upgrade_report(
    config: AppConfig,
    plan: dict[str, Any],
    status: str,
    *,
    applied: bool,
    message: str,
    steps: list[dict[str, Any]] | None = None,
    backup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": status,
        "applied": applied,
        "message": message,
        "plan": plan,
        "steps": steps or [],
        "pre_upgrade_backup": backup,
        "source_media_preserved": True,
    }
    client = {
        "version": 1,
        "updated_at": report["updated_at"],
        "local_only": True,
        "status": "Ready" if status == "pass" else ("Needs Attention" if status == "warn" else "Blocked"),
        "upgrade_required": bool(plan.get("migrations")),
        "target_version": plan.get("target_app_version"),
        "message": message,
        "source_media_preserved": True,
        "next_action": "Run upgrade apply" if plan.get("migrations") and not applied else "Continue",
    }
    save_json_file(config.analytics_dir / "upgrade_report.json", report)
    save_json_file(config.analytics_dir / "client_upgrade_status.json", client)
    return report
