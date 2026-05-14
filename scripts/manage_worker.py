#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.worker_runtime import (
    cleanup_stale,
    health,
    heartbeat,
    request_pause,
    request_resume,
    request_stop,
    start_session,
    stop_session,
    terminate_pid,
)


def _run_once(root: Path) -> dict[str, object]:
    result = subprocess.run(["python3", "scripts/run_task_worker.py", "--once"], cwd=root, capture_output=True, text=True, timeout=300)
    return {"status": "pass" if result.returncode == 0 else "fail", "returncode": result.returncode, "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]}


def start_worker(root: Path, interval: float) -> dict[str, object]:
    config = load_config(root)
    current = cleanup_stale(config)
    if current.get("pid_running") and current.get("state") not in {"stopped", "failed", "stale"}:
        return {"status": "pass", "message": "worker already running", "worker": current}
    log_path = config.logs_dir / "worker_runtime.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        ["python3", "scripts/run_task_worker.py", "--interval", str(interval), "--max-tasks", "100000"],
        cwd=root,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    worker = start_session(config, pid=process.pid, command="scripts/run_task_worker.py", state="starting")
    return {"status": "pass", "message": "worker started", "worker": worker, "log_path": str(log_path)}


def stop_worker(root: Path) -> dict[str, object]:
    config = load_config(root)
    current = request_stop(config)
    terminated = terminate_pid(current.get("pid"))
    if not terminated:
        stop_session(config, reason="no running process")
    return {"status": "pass", "stop_requested": True, "terminated": terminated, "worker": health(config)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage HigherKey local task worker.")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "once", "pause", "resume", "heartbeat", "cleanup-stale"])
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--interval", type=float, default=10.0, help="Worker polling interval for start/restart.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config = load_config(root)
    if args.command == "start":
        result = start_worker(root, args.interval)
    elif args.command == "stop":
        result = stop_worker(root)
    elif args.command == "restart":
        stop_worker(root)
        result = start_worker(root, args.interval)
    elif args.command == "status":
        result = {"status": "pass", "worker": health(config)}
    elif args.command == "once":
        result = _run_once(root)
    elif args.command == "pause":
        result = {"status": "pass", "worker": request_pause(config)}
    elif args.command == "resume":
        result = {"status": "pass", "worker": request_resume(config)}
    elif args.command == "heartbeat":
        result = {"status": "pass", "worker": heartbeat(config)}
    else:
        result = {"status": "pass", "worker": cleanup_stale(config)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
