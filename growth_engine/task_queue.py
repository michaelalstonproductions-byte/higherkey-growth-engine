from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig
from .events import append_event
from .index import utc_now
from .runtime_db import connect, migrate


TASK_STATUSES = {"queued", "scheduled", "running", "completed", "failed", "cancelled", "retrying", "blocked"}
PRIORITIES = {"high": 0, "normal": 1, "low": 2}
TASK_TYPES = {
    "repair_project_media",
    "run_pipeline",
    "rebuild_metadata_index",
    "build_media_cache",
    "run_orchestrator",
    "run_color_school",
    "run_audio_school",
    "build_runtime_snapshot",
    "export_approved_posts",
    "export_social_packs",
    "run_diagnostics",
    "run_full_qa",
    "maintenance",
    "backup_project",
    "restore_project",
    "reset_demo_workspace",
    "archive_project_artifacts",
    "validate_project",
    "project_size_report",
    "storage_report",
    "cleanup_plan",
    "cleanup_apply",
    "archive_generated_artifacts",
    "vacuum_runtime_db",
}


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True)


def _load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _task_id(task_type: str, payload: dict[str, Any], source: str | None = None) -> str:
    digest = hashlib.sha1()
    digest.update(task_type.encode("utf-8"))
    digest.update(_json(payload).encode("utf-8"))
    digest.update(str(source or "").encode("utf-8"))
    digest.update(utc_now().encode("utf-8"))
    return f"task_{digest.hexdigest()[:16]}"


def _attempt_id(task_id: str, attempt_number: int) -> str:
    return f"attempt_{task_id}_{attempt_number}"


def _row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = _load(item.pop("payload_json", None))
    item["result"] = _load(item.pop("result_json", None))
    item["error"] = _load(item.pop("error_json", None))
    item["output_summary"] = _load(item.pop("output_summary_json", None))
    item["visible_to_client"] = bool(item.get("visible_to_client", 1))
    item["cancellation_requested"] = bool(item.get("cancellation_requested", 0))
    item["retryable"] = bool(item.get("retryable", 1))
    return item


def _now_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def enqueue_task(
    config: AppConfig,
    task_type: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: str = "normal",
    scheduled_for: str | None = None,
    max_attempts: int = 3,
    lock_key: str | None = None,
    parent_task_id: str | None = None,
    started_by: str | None = None,
    visible_to_client: bool = True,
    client_message: str | None = None,
    source: str = "task_queue",
) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ValueError(f"unsupported task type: {task_type}")
    if priority not in PRIORITIES:
        raise ValueError(f"unsupported priority: {priority}")
    status = "scheduled" if scheduled_for else "queued"
    task_id = _task_id(task_type, payload or {}, source)
    now = utc_now()
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            """
            INSERT INTO task_queue (
                task_id, task_type, status, priority, payload_json, result_json, error_json,
                created_at, updated_at, scheduled_for, attempts, max_attempts, lock_key,
                parent_task_id, source, progress_percent, current_stage, stage_message,
                started_by, visible_to_client, client_message, warning_count, skipped_count,
                output_summary_json, cancellation_requested, retryable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0, 0, ?, 0, 1)
            """,
            (
                task_id,
                task_type,
                status,
                priority,
                _json(payload or {}),
                None,
                None,
                now,
                now,
                scheduled_for,
                max_attempts,
                lock_key,
                parent_task_id,
                source,
                "scheduled" if scheduled_for else "queued",
                client_message or _client_message(task_type, "queued"),
                started_by,
                1 if visible_to_client else 0,
                client_message or _client_message(task_type, "queued"),
                _json({}),
            ),
        )
        connection.commit()
    task = get_task(config, task_id) or {}
    append_event(config, "task.enqueued", severity="info", source=source, related_ids={"task_id": task_id}, summary={"task_type": task_type, "status": status})
    write_audit_event(config, "task.enqueued", source=source, summary={"task_id": task_id, "task_type": task_type, "status": status})
    return task


def get_task(config: AppConfig, task_id: str) -> dict[str, Any] | None:
    with connect(config) as connection:
        migrate(connection)
        row = connection.execute("SELECT * FROM task_queue WHERE task_id = ?", (task_id,)).fetchone()
    return _row(row) if row else None


def list_tasks(config: AppConfig, *, status: str | None = None, task_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    clauses = []
    values: list[Any] = []
    if status:
        clauses.append("status = ?")
        values.append(status)
    if task_type:
        clauses.append("task_type = ?")
        values.append(task_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(config) as connection:
        migrate(connection)
        rows = connection.execute(
            f"SELECT * FROM task_queue {where} ORDER BY updated_at DESC LIMIT ?",
            (*values, limit),
        ).fetchall()
    return [_row(row) for row in rows]


def add_dependency(config: AppConfig, task_id: str, depends_on_task_id: str) -> None:
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            "INSERT OR IGNORE INTO task_dependencies(task_id, depends_on_task_id, created_at) VALUES (?, ?, ?)",
            (task_id, depends_on_task_id, utc_now()),
        )
        connection.commit()


def dependencies_satisfied(config: AppConfig, task_id: str) -> bool:
    with connect(config) as connection:
        migrate(connection)
        rows = connection.execute(
            """
            SELECT q.status
            FROM task_dependencies d
            JOIN task_queue q ON q.task_id = d.depends_on_task_id
            WHERE d.task_id = ?
            """,
            (task_id,),
        ).fetchall()
    return all(row["status"] == "completed" for row in rows)


def cancel_task(config: AppConfig, task_id: str, reason: str = "cancelled") -> dict[str, Any] | None:
    now = utc_now()
    task = get_task(config, task_id)
    if task and task.get("status") == "running":
        with connect(config) as connection:
            migrate(connection)
            connection.execute(
                "UPDATE task_queue SET cancellation_requested = 1, client_message = ?, updated_at = ?, error_json = ? WHERE task_id = ?",
                ("Cancellation requested. Current stage can finish safely.", now, _json({"reason": reason}), task_id),
            )
            connection.commit()
        append_event(config, "task.cancel_requested", severity="warn", source="task_queue", related_ids={"task_id": task_id}, summary={"reason": reason})
        return get_task(config, task_id)
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            "UPDATE task_queue SET status = 'cancelled', cancelled_at = ?, updated_at = ?, error_json = ? WHERE task_id = ? AND status NOT IN ('completed', 'cancelled')",
            (now, now, _json({"reason": reason}), task_id),
        )
        connection.commit()
    task = get_task(config, task_id)
    append_event(config, "task.cancelled", severity="warn", source="task_queue", related_ids={"task_id": task_id}, summary={"reason": reason})
    return task


def claim_next_task(config: AppConfig, *, task_type: str | None = None) -> dict[str, Any] | None:
    now = utc_now()
    now_seconds = _now_seconds(now)
    with connect(config) as connection:
        migrate(connection)
        clauses = ["status IN ('queued', 'scheduled', 'retrying')"]
        values: list[Any] = []
        if task_type:
            clauses.append("task_type = ?")
            values.append(task_type)
        rows = connection.execute(
            f"""
            SELECT * FROM task_queue
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     COALESCE(scheduled_for, created_at) ASC,
                     created_at ASC
            """,
            values,
        ).fetchall()
        for row in rows:
            task = _row(row)
            scheduled = task.get("scheduled_for")
            if scheduled and _now_seconds(scheduled) > now_seconds:
                continue
            if not dependencies_satisfied(config, task["task_id"]):
                connection.execute("UPDATE task_queue SET status = 'blocked', updated_at = ? WHERE task_id = ?", (now, task["task_id"]))
                continue
            attempts = int(task.get("attempts") or 0) + 1
            connection.execute(
                """
                UPDATE task_queue
                SET status = 'running', attempts = ?, started_at = ?, updated_at = ?,
                    progress_percent = 5, current_stage = ?, stage_message = ?, client_message = ?
                WHERE task_id = ?
                """,
                (attempts, now, now, task["task_type"], _client_message(task["task_type"], "running"), _client_message(task["task_type"], "running"), task["task_id"]),
            )
            connection.execute(
                "INSERT OR REPLACE INTO task_attempts(attempt_id, task_id, attempt_number, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                (_attempt_id(task["task_id"], attempts), task["task_id"], attempts, now),
            )
            connection.commit()
            claimed = get_task(config, task["task_id"])
            append_event(config, "task.claimed", severity="info", source="task_queue", related_ids={"task_id": task["task_id"]}, summary={"task_type": task["task_type"], "attempt": attempts})
            return claimed
        connection.commit()
    return None


def complete_task(config: AppConfig, task_id: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    now = utc_now()
    task = get_task(config, task_id)
    attempt = int(task.get("attempts") or 1) if task else 1
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            """
            UPDATE task_queue
            SET status = 'completed', result_json = ?, output_summary_json = ?,
                completed_at = ?, updated_at = ?, progress_percent = 100,
                current_stage = 'completed', stage_message = ?, client_message = ?
            WHERE task_id = ?
            """,
            (_json(result or {}), _json(_safe_summary(result or {})), now, now, "Ready for review", _client_message(task.get("task_type") if task else "", "completed"), task_id),
        )
        connection.execute(
            "UPDATE task_attempts SET status = 'completed', completed_at = ?, result_json = ? WHERE attempt_id = ?",
            (now, _json(result or {}), _attempt_id(task_id, attempt)),
        )
        connection.execute("UPDATE task_queue SET status = 'queued', updated_at = ? WHERE status = 'blocked'", (now,))
        connection.commit()
    append_event(config, "task.completed", severity="info", source="task_queue", related_ids={"task_id": task_id}, summary=result or {})
    write_audit_event(config, "task.completed", source="task_queue", summary={"task_id": task_id, "task_type": task.get("task_type") if task else None})
    return get_task(config, task_id)


def fail_task(config: AppConfig, task_id: str, error: dict[str, Any] | None = None) -> dict[str, Any] | None:
    now = utc_now()
    task = get_task(config, task_id)
    if not task:
        return None
    attempts = int(task.get("attempts") or 0)
    max_attempts = int(task.get("max_attempts") or 1)
    retryable = bool((error or {}).get("retryable", task.get("retryable", True)))
    status = "retrying" if retryable and attempts < max_attempts else "failed"
    next_retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** max(attempts, 1)))).isoformat(timespec="seconds") if status == "retrying" else None
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            """
            UPDATE task_queue
            SET status = ?, error_json = ?, updated_at = ?, current_stage = ?,
                stage_message = ?, client_message = ?, warning_count = ?, skipped_count = ?,
                retryable = ?, next_retry_at = ?
            WHERE task_id = ?
            """,
            (
                status,
                _json(error or {}),
                now,
                "retrying" if status == "retrying" else "failed",
                (error or {}).get("client_message") or "Needs attention. See diagnostics for details.",
                (error or {}).get("client_message") or "Needs attention. See diagnostics for details.",
                int((error or {}).get("warning_count", 0) or 0),
                int((error or {}).get("skipped_count", 0) or 0),
                1 if retryable else 0,
                next_retry_at,
                task_id,
            ),
        )
        connection.execute(
            "UPDATE task_attempts SET status = ?, completed_at = ?, error_json = ? WHERE attempt_id = ?",
            (status, now, _json(error or {}), _attempt_id(task_id, attempts)),
        )
        connection.commit()
    append_event(config, "task.failed" if status == "failed" else "task.retrying", severity="fail" if status == "failed" else "warn", source="task_queue", related_ids={"task_id": task_id}, summary=error or {})
    return get_task(config, task_id)


def retry_task(config: AppConfig, task_id: str) -> dict[str, Any] | None:
    now = utc_now()
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            "UPDATE task_queue SET status = 'retrying', updated_at = ?, cancellation_requested = 0, client_message = ? WHERE task_id = ?",
            (now, "Retry queued.", task_id),
        )
        connection.commit()
    return get_task(config, task_id)


def update_task_progress(
    config: AppConfig,
    task_id: str,
    *,
    progress_percent: int | None = None,
    current_stage: str | None = None,
    stage_message: str | None = None,
    client_message: str | None = None,
    warning_count: int | None = None,
    skipped_count: int | None = None,
    output_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    fields = ["updated_at = ?"]
    values: list[Any] = [utc_now()]
    updates = {
        "progress_percent": progress_percent,
        "current_stage": current_stage,
        "stage_message": stage_message,
        "client_message": client_message,
        "warning_count": warning_count,
        "skipped_count": skipped_count,
        "output_summary_json": _json(output_summary) if output_summary is not None else None,
    }
    for key, value in updates.items():
        if value is not None:
            fields.append(f"{key} = ?")
            values.append(value)
    values.append(task_id)
    with connect(config) as connection:
        migrate(connection)
        connection.execute(f"UPDATE task_queue SET {', '.join(fields)} WHERE task_id = ?", values)
        connection.commit()
    return get_task(config, task_id)


def task_summary(config: AppConfig) -> dict[str, Any]:
    with connect(config) as connection:
        migrate(connection)
        rows = connection.execute("SELECT status, COUNT(*) AS count FROM task_queue GROUP BY status").fetchall()
        type_rows = connection.execute("SELECT task_type, status, COUNT(*) AS count FROM task_queue GROUP BY task_type, status").fetchall()
        current = connection.execute("SELECT * FROM task_queue WHERE status = 'running' ORDER BY started_at DESC LIMIT 1").fetchone()
        next_task = connection.execute(
            """
            SELECT * FROM task_queue
            WHERE status IN ('queued', 'scheduled', 'retrying', 'blocked')
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     COALESCE(scheduled_for, created_at) ASC
            LIMIT 1
            """
        ).fetchone()
    counts = {status: 0 for status in TASK_STATUSES}
    counts.update({row["status"]: int(row["count"]) for row in rows})
    completed = counts.get("completed", 0)
    total = sum(counts.values())
    return {
        "updated_at": utc_now(),
        "counts": counts,
        "by_type": [dict(row) for row in type_rows],
        "current_task": _row(current) if current else None,
        "next_task": _row(next_task) if next_task else None,
        "progress_percentage": int(round((completed / total) * 100)) if total else 0,
        "total": total,
        "local_only": True,
    }


def _client_message(task_type: str, status: str) -> str:
    if status == "completed":
        return {
            "repair_project_media": "Project media repaired.",
            "run_pipeline": "Ready for review.",
            "rebuild_metadata_index": "Metadata indexed.",
            "build_media_cache": "Thumbnails ready.",
            "run_color_school": "Color readiness complete.",
            "run_audio_school": "Audio readiness complete.",
            "run_orchestrator": "Agents updated.",
            "build_runtime_snapshot": "Runtime state updated.",
            "export_social_packs": "Social export packs prepared.",
            "backup_project": "Project backup complete.",
            "restore_project": "Project restore complete.",
            "reset_demo_workspace": "Demo workspace reset complete.",
            "archive_project_artifacts": "Project artifacts archived.",
            "validate_project": "Project validation complete.",
            "project_size_report": "Project size report complete.",
        }.get(task_type, "Task complete.")
    return {
        "repair_project_media": "Checking project media",
        "run_pipeline": "Creating clips",
        "rebuild_metadata_index": "Indexing metadata",
        "build_media_cache": "Building thumbnails",
        "run_orchestrator": "Updating agents",
        "run_color_school": "Analyzing color",
        "run_audio_school": "Analyzing audio",
        "build_runtime_snapshot": "Updating runtime state",
        "export_approved_posts": "Preparing approved exports",
        "export_social_packs": "Preparing social exports",
        "run_diagnostics": "Running diagnostics",
        "run_full_qa": "Running local QA",
        "maintenance": "Running maintenance",
        "backup_project": "Backing up project",
        "restore_project": "Restoring project",
        "reset_demo_workspace": "Resetting demo workspace",
        "archive_project_artifacts": "Archiving project artifacts",
        "validate_project": "Validating project",
        "project_size_report": "Building project size report",
    }.get(task_type, "Processing task")


def _safe_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"stdout_tail", "stderr_tail", "stdout", "stderr", "command"}
    }


def upsert_schedule(
    config: AppConfig,
    schedule_id: str,
    task_type: str,
    cadence: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: str = "normal",
    next_run_at: str | None = None,
    enabled: bool = True,
    source: str = "schedule_tasks",
) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ValueError(f"unsupported task type: {task_type}")
    now = utc_now()
    with connect(config) as connection:
        migrate(connection)
        connection.execute(
            """
            INSERT INTO task_schedules(schedule_id, task_type, cadence, payload_json, priority, enabled, next_run_at, created_at, updated_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(schedule_id) DO UPDATE SET
                task_type=excluded.task_type,
                cadence=excluded.cadence,
                payload_json=excluded.payload_json,
                priority=excluded.priority,
                enabled=excluded.enabled,
                next_run_at=excluded.next_run_at,
                updated_at=excluded.updated_at,
                source=excluded.source
            """,
            (schedule_id, task_type, cadence, _json(payload or {}), priority, 1 if enabled else 0, next_run_at, now, now, source),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM task_schedules WHERE schedule_id = ?", (schedule_id,)).fetchone()
    return dict(row)


def list_schedules(config: AppConfig) -> list[dict[str, Any]]:
    with connect(config) as connection:
        migrate(connection)
        rows = connection.execute("SELECT * FROM task_schedules ORDER BY schedule_id").fetchall()
    schedules = []
    for row in rows:
        item = dict(row)
        item["payload"] = _load(item.pop("payload_json", None))
        item["enabled"] = bool(item["enabled"])
        schedules.append(item)
    return schedules
