from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any

from .config import AppConfig
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file


WORKER_STATES = {"stopped", "starting", "idle", "running", "paused", "stopping", "failed", "stale"}
STALE_SECONDS = 120


def status_path(config: AppConfig) -> Path:
    return config.analytics_dir / "worker_runtime_status.json"


def history_path(config: AppConfig) -> Path:
    return config.analytics_dir / "worker_runtime_history.json"


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
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


def read_status(config: AppConfig) -> dict[str, Any]:
    return load_json_file(status_path(config), {"state": "stopped", "local_only": True})


def write_status(config: AppConfig, state: str, **updates: Any) -> dict[str, Any]:
    if state not in WORKER_STATES:
        raise ValueError(f"invalid worker state: {state}")
    current = read_status(config)
    payload = {
        **current,
        **updates,
        "version": 1,
        "state": state,
        "updated_at": utc_now(),
        "project_root": str(config.root),
        "local_only": True,
    }
    save_json_file(status_path(config), payload)
    return payload


def append_history(config: AppConfig, entry: dict[str, Any]) -> None:
    history = load_json_file(history_path(config), {"version": 1, "events": []})
    history.setdefault("events", []).append({**entry, "at": utc_now()})
    history["events"] = history["events"][-300:]
    history["updated_at"] = utc_now()
    save_json_file(history_path(config), history)


def start_session(config: AppConfig, *, pid: int | None = None, command: str | None = None, state: str = "starting") -> dict[str, Any]:
    payload = write_status(
        config,
        state,
        pid=pid or os.getpid(),
        command=command or "",
        started_at=utc_now(),
        heartbeat_at=utc_now(),
        stop_requested=False,
        pause_requested=False,
    )
    append_history(config, {"event": "started", "pid": payload.get("pid"), "command": command})
    append_event(config, "worker.started", severity="info", source="worker_runtime", summary={"pid": payload.get("pid"), "state": state})
    return payload


def heartbeat(config: AppConfig, *, state: str | None = None, current_task_id: str | None = None) -> dict[str, Any]:
    current = read_status(config)
    payload = write_status(
        config,
        state or current.get("state", "running"),
        heartbeat_at=utc_now(),
        current_task_id=current_task_id if current_task_id is not None else current.get("current_task_id"),
    )
    append_event(config, "worker.heartbeat", severity="info", source="worker_runtime", summary={"state": payload.get("state"), "current_task_id": payload.get("current_task_id")})
    return payload


def stop_session(config: AppConfig, *, reason: str = "stopped") -> dict[str, Any]:
    payload = write_status(config, "stopped", stopped_at=utc_now(), stop_requested=False, current_task_id=None, reason=reason)
    append_history(config, {"event": "stopped", "reason": reason})
    append_event(config, "worker.stopped", severity="info", source="worker_runtime", summary={"reason": reason})
    return payload


def request_stop(config: AppConfig) -> dict[str, Any]:
    payload = write_status(config, "stopping", stop_requested=True)
    append_event(config, "worker.stopped", severity="info", source="worker_runtime", summary={"requested": True})
    return payload


def request_pause(config: AppConfig) -> dict[str, Any]:
    payload = write_status(config, "paused", pause_requested=True)
    append_history(config, {"event": "paused"})
    append_event(config, "worker.paused", severity="info", source="worker_runtime", summary={"requested": True})
    return payload


def request_resume(config: AppConfig) -> dict[str, Any]:
    payload = write_status(config, "idle", pause_requested=False)
    append_history(config, {"event": "resumed"})
    append_event(config, "worker.resumed", severity="info", source="worker_runtime", summary={"requested": True})
    return payload


def health(config: AppConfig) -> dict[str, Any]:
    status = read_status(config)
    pid = int(status.get("pid") or 0)
    running = _pid_running(pid)
    heartbeat_age = time.time() - _stamp_seconds(status.get("heartbeat_at")) if status.get("heartbeat_at") else None
    stale = bool(status.get("state") not in {"stopped", "failed"} and ((heartbeat_age is not None and heartbeat_age > STALE_SECONDS) or (pid and not running)))
    return {
        **status,
        "pid_running": running,
        "heartbeat_age_seconds": round(heartbeat_age, 3) if heartbeat_age is not None else None,
        "health": "stale" if stale else ("running" if running else status.get("state", "stopped")),
        "stale": stale,
    }


def cleanup_stale(config: AppConfig) -> dict[str, Any]:
    current = health(config)
    if current.get("stale"):
        payload = write_status(config, "stale", stale_detected_at=utc_now(), stop_requested=False, pause_requested=False)
        append_history(config, {"event": "stale_detected", "pid": current.get("pid")})
        append_event(config, "worker.stale_detected", severity="warn", source="worker_runtime", summary={"pid": current.get("pid")})
        return payload
    return current


def terminate_pid(pid: int | None) -> bool:
    if not pid or not _pid_running(pid):
        return False
    os.kill(int(pid), signal.SIGTERM)
    return True
