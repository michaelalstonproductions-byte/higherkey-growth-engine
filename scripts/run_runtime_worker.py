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
from growth_engine.events import append_event
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.runtime_lock import acquire_lock, release_lock


TASKS = (
    ("repair_project_media", ["python3", "scripts/repair_project_media.py"]),
    ("backfill_runtime_db", ["python3", "scripts/backfill_runtime_db.py", "--quick"]),
    ("build_runtime_snapshot", ["python3", "scripts/build_runtime_snapshot.py"]),
    ("rebuild_metadata_index", ["python3", "scripts/rebuild_metadata_index.py"]),
)


def run_task(name: str, args: list[str], root: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(root)}
    started = utc_now()
    try:
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=180)
        return {
            "name": name,
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "started_at": started,
            "completed_at": utc_now(),
            "stdout_tail": result.stdout[-1000:],
            "stderr_tail": result.stderr[-1000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "status": "failed",
            "started_at": started,
            "completed_at": utc_now(),
            "timeout_seconds": 180,
            "stdout_tail": str(exc.stdout or "")[-1000:],
            "stderr_tail": str(exc.stderr or "")[-1000:],
        }


def append_history(root: Path, cycle: dict[str, Any]) -> None:
    path = root / "analytics" / "runtime_worker_history.json"
    history = load_json_file(path, {"version": 1, "cycles": []})
    history.setdefault("cycles", []).append(cycle)
    history["cycles"] = history["cycles"][-100:]
    history["updated_at"] = utc_now()
    save_json_file(path, history)


def run_cycle(root: Path, *, force: bool = False) -> dict[str, Any]:
    config = load_config(root)
    lock = acquire_lock(config, "run_runtime_worker", force=force)
    try:
        results = [run_task(name, args, config.root) for name, args in TASKS]
        status = "failed" if any(item["status"] == "failed" for item in results) else "completed"
        cycle = {
            "version": 1,
            "updated_at": utc_now(),
            "status": status,
            "lock": lock,
            "tasks": results,
            "local_only": True,
        }
        save_json_file(config.analytics_dir / "runtime_worker_status.json", cycle)
        append_history(config.root, cycle)
        append_event(config, "agent.completed", severity="fail" if status == "failed" else "info", source="run_runtime_worker", summary={"status": status, "tasks": len(results)})
        return cycle
    finally:
        release_lock(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey local runtime worker.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--once", action="store_true", help="Run one deterministic worker cycle and exit.")
    parser.add_argument("--interval", type=float, default=30.0, help="Polling interval when not using --once.")
    parser.add_argument("--force", action="store_true", help="Force stale/active runtime lock replacement.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    while True:
        cycle = run_cycle(root, force=args.force)
        print(json.dumps(cycle, indent=2, sort_keys=True))
        if args.once:
            return 0 if cycle["status"] != "failed" else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
