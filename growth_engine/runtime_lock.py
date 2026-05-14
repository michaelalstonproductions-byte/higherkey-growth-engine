from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


STALE_SECONDS = 60 * 60


def lock_path(config: AppConfig) -> Path:
    return config.analytics_dir / "runtime.lock"


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stamp_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def read_lock(config: AppConfig) -> dict[str, Any]:
    return load_json_file(lock_path(config), {})


def is_stale(lock: dict[str, Any], now_seconds: float | None = None) -> bool:
    now = now_seconds or __import__("time").time()
    heartbeat = _stamp_seconds(lock.get("heartbeat_at") or lock.get("started_at"))
    pid = int(lock.get("pid") or 0)
    if heartbeat and now - heartbeat > STALE_SECONDS:
        return True
    return bool(pid and not _pid_running(pid))


def acquire_lock(config: AppConfig, command: str, *, force: bool = False) -> dict[str, Any]:
    path = lock_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_lock(config)
    if existing and not force and not is_stale(existing):
        raise RuntimeError(f"runtime lock active for {existing.get('command')} pid {existing.get('pid')}")
    if existing and (force or is_stale(existing)):
        path.unlink(missing_ok=True)
    payload = {
        "pid": os.getpid(),
        "command": command,
        "started_at": utc_now(),
        "heartbeat_at": utc_now(),
        "project_root": str(config.root),
    }
    save_json_file(path, payload)
    return payload


def heartbeat(config: AppConfig) -> dict[str, Any]:
    lock = read_lock(config)
    if lock:
        lock["heartbeat_at"] = utc_now()
        save_json_file(lock_path(config), lock)
    return lock


def release_lock(config: AppConfig) -> None:
    lock = read_lock(config)
    if not lock or int(lock.get("pid") or 0) == os.getpid():
        lock_path(config).unlink(missing_ok=True)
