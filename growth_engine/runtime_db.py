from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import AppConfig
from .index import utc_now


SCHEMA_VERSION = 4
TABLES = (
    "projects",
    "media_assets",
    "clips",
    "jobs",
    "events",
    "packages",
    "social_exports",
    "diagnostics",
    "school_reports",
    "pipeline_runs",
    "agent_runs",
)
TASK_TABLES = (
    "task_queue",
    "task_attempts",
    "task_dependencies",
    "task_schedules",
)


def db_path(config: AppConfig) -> Path:
    return config.analytics_dir / "runtime_state.db"


def connect(config: AppConfig) -> sqlite3.Connection:
    config.analytics_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(config))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    for table in TABLES:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                type TEXT,
                status TEXT,
                severity TEXT,
                source TEXT,
                path TEXT,
                related_id TEXT,
                summary_json TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_project ON {table}(project_id)")
        connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_updated ON {table}(updated_at)")
        connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table}(status)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_queue (
            task_id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            scheduled_for TEXT,
            started_at TEXT,
            completed_at TEXT,
            cancelled_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            lock_key TEXT,
            parent_task_id TEXT,
            source TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_type ON task_queue(task_type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_schedule ON task_queue(scheduled_for)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_attempts (
            attempt_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_json TEXT,
            error_json TEXT,
            FOREIGN KEY(task_id) REFERENCES task_queue(task_id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_attempts_task ON task_attempts(task_id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_dependencies (
            task_id TEXT NOT NULL,
            depends_on_task_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(task_id, depends_on_task_id),
            FOREIGN KEY(task_id) REFERENCES task_queue(task_id),
            FOREIGN KEY(depends_on_task_id) REFERENCES task_queue(task_id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends ON task_dependencies(depends_on_task_id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_schedules (
            schedule_id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            cadence TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            priority TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            next_run_at TEXT,
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_task_schedules_enabled ON task_schedules(enabled)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            actor TEXT,
            severity TEXT NOT NULL,
            source TEXT NOT NULL,
            project_root TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at)")
    _ensure_column(connection, "task_queue", "progress_percent", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "task_queue", "current_stage", "TEXT")
    _ensure_column(connection, "task_queue", "stage_message", "TEXT")
    _ensure_column(connection, "task_queue", "started_by", "TEXT")
    _ensure_column(connection, "task_queue", "visible_to_client", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "task_queue", "client_message", "TEXT")
    _ensure_column(connection, "task_queue", "warning_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "task_queue", "skipped_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "task_queue", "output_summary_json", "TEXT")
    _ensure_column(connection, "task_queue", "cancellation_requested", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "task_queue", "retryable", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "task_queue", "next_retry_at", "TEXT")
    connection.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, utc_now()),
    )
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db(config: AppConfig) -> Path:
    with connect(config) as connection:
        migrate(connection)
    return db_path(config)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True)


def upsert_record(
    connection: sqlite3.Connection,
    table: str,
    *,
    record_id: str,
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    path: str | None = None,
    related_id: str | None = None,
    summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> None:
    if table not in TABLES:
        raise ValueError(f"unknown runtime table: {table}")
    now = utc_now()
    connection.execute(
        f"""
        INSERT INTO {table} (
            id, project_id, type, status, severity, source, path, related_id,
            summary_json, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_id=excluded.project_id,
            type=excluded.type,
            status=excluded.status,
            severity=excluded.severity,
            source=excluded.source,
            path=excluded.path,
            related_id=excluded.related_id,
            summary_json=excluded.summary_json,
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at
        """,
        (
            record_id,
            project_id,
            type,
            status,
            severity,
            source,
            path,
            related_id,
            _json(summary),
            _json(metadata),
            created_at or now,
            updated_at or now,
        ),
    )


def upsert_many(connection: sqlite3.Connection, table: str, records: Iterable[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        upsert_record(connection, table, **record)
        count += 1
    return count


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in (*TABLES, *TASK_TABLES)}


def latest_records(connection: sqlite3.Connection, table: str, limit: int = 10) -> list[dict[str, Any]]:
    if table not in TABLES:
        raise ValueError(f"unknown runtime table: {table}")
    rows = connection.execute(
        f"SELECT * FROM {table} ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
