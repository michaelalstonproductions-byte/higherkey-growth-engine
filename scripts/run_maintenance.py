#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.audit import write_audit_event
from growth_engine.config import load_config
from growth_engine.events import append_event
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file
from growth_engine.runtime_db import connect
from growth_engine.runtime_lock import acquire_lock, release_lock


def run_step(name: str, args: list[str], root: Path, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"name": name, "status": "pass", "dry_run": True, "args": args}
    env = {**os.environ, "PYTHONPATH": str(root)}
    try:
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=180)
        return {
            "name": name,
            "status": "pass" if result.returncode == 0 else "fail",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {"name": name, "status": "warn", "timeout_seconds": 180, "stdout_tail": str(exc.stdout or "")[-2000:], "stderr_tail": str(exc.stderr or "")[-2000:]}


def run_maintenance(root: Path, *, dry_run: bool = False, vacuum: bool = False, force: bool = False) -> dict[str, Any]:
    config = load_config(root)
    lock = None
    if not dry_run:
        lock = acquire_lock(config, "run_maintenance", force=force)
    try:
        steps = [
            ("cleanup_stale_worker", ["python3", "scripts/manage_worker.py", "cleanup-stale"]),
            ("repair_project_media", ["python3", "scripts/repair_project_media.py"]),
            ("backfill_runtime_db", ["python3", "scripts/backfill_runtime_db.py", "--quick"]),
            ("reconcile_runtime_state", ["python3", "scripts/reconcile_runtime_state.py", "--dry-run"]),
            ("security_check", ["python3", "scripts/run_security_check.py"]),
            ("storage_report", ["python3", "scripts/manage_storage.py", "report"]),
            ("cleanup_plan", ["python3", "scripts/manage_storage.py", "plan", "--dry-run"]),
            ("upgrade_check", ["python3", "scripts/upgrade_project.py", "--check"]),
            ("data_contract_validation", ["python3", "scripts/validate_data_contract.py"]),
            ("launch_preflight", ["python3", "scripts/run_launch_preflight.py"]),
            ("build_runtime_snapshot", ["python3", "scripts/build_runtime_snapshot.py"]),
            ("build_task_snapshot", ["python3", "scripts/build_task_snapshot.py"]),
            ("build_observability_report", ["python3", "scripts/build_observability_report.py"]),
            ("diagnostics", ["python3", "scripts/run_diagnostics.py"]),
        ]
        results = [run_step(name, args, config.root, dry_run) for name, args in steps]
        if vacuum and not dry_run:
            with connect(config) as connection:
                connection.execute("VACUUM")
            results.append({"name": "runtime_db_vacuum", "status": "pass"})
        status = "fail" if any(item.get("status") == "fail" for item in results) else ("warn" if any(item.get("status") == "warn" for item in results) else "pass")
        report = {
            "version": 1,
            "updated_at": utc_now(),
            "status": status,
            "dry_run": dry_run,
            "lock": lock,
            "steps": results,
            "local_only": True,
        }
        save_json_file(config.analytics_dir / "maintenance_report.json", report)
        append_event(config, "repair.completed", severity=status, source="run_maintenance", summary={"status": status, "dry_run": dry_run})
        write_audit_event(config, "maintenance.run", severity=status, source="run_maintenance", summary={"status": status, "dry_run": dry_run})
        return report
    finally:
        if not dry_run:
            release_lock(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey local maintenance tasks.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", help="Report maintenance stages without executing them.")
    parser.add_argument("--vacuum", action="store_true", help="Vacuum runtime SQLite database after maintenance.")
    parser.add_argument("--force", action="store_true", help="Force stale/active runtime lock replacement.")
    args = parser.parse_args()
    report = run_maintenance(Path(args.root).resolve(), dry_run=args.dry_run, vacuum=args.vacuum, force=args.force)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
