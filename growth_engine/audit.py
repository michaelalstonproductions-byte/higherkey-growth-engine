from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import utc_now
from .runtime_db import connect, migrate


AUDIT_FILE = "audit_log.jsonl"


def audit_log_path(config: AppConfig) -> Path:
    return config.analytics_dir / AUDIT_FILE


def _audit_id(timestamp: str, event_type: str, source: str, summary: dict[str, Any]) -> str:
    digest = hashlib.sha1()
    digest.update(timestamp.encode("utf-8"))
    digest.update(event_type.encode("utf-8"))
    digest.update(source.encode("utf-8"))
    digest.update(json.dumps(summary, sort_keys=True).encode("utf-8"))
    return f"audit_{digest.hexdigest()[:16]}"


def write_audit_event(
    config: AppConfig,
    event_type: str,
    *,
    actor: str = "local_operator",
    severity: str = "info",
    source: str = "runtime",
    summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = utc_now()
    summary_payload = summary or {}
    payload = {
        "audit_id": _audit_id(timestamp, event_type, source, summary_payload),
        "timestamp": timestamp,
        "type": event_type,
        "actor": actor,
        "severity": severity,
        "source": source,
        "project_root": str(config.root),
        "summary": summary_payload,
        "metadata": metadata or {},
        "local_only": True,
    }
    path = audit_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    try:
        with connect(config) as connection:
            migrate(connection)
            connection.execute(
                """
                INSERT OR REPLACE INTO audit_events (
                    audit_id, event_type, actor, severity, source, project_root,
                    summary_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["audit_id"],
                    event_type,
                    actor,
                    severity,
                    source,
                    str(config.root),
                    json.dumps(summary_payload, sort_keys=True),
                    json.dumps(payload["metadata"], sort_keys=True),
                    timestamp,
                ),
            )
            connection.commit()
    except Exception:
        # JSONL remains the append-only audit source of truth.
        pass
    return payload


def read_recent_audit_events(config: AppConfig, limit: int = 50) -> list[dict[str, Any]]:
    path = audit_log_path(config)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)) :]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def audit_summary(config: AppConfig) -> dict[str, Any]:
    events = read_recent_audit_events(config, limit=500)
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for event in events:
        by_type[event.get("type", "unknown")] = by_type.get(event.get("type", "unknown"), 0) + 1
        by_severity[event.get("severity", "info")] = by_severity.get(event.get("severity", "info"), 0) + 1
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "audit_log": str(audit_log_path(config)),
        "recent_count": len(events),
        "by_type": by_type,
        "by_severity": by_severity,
        "latest": events[-10:],
    }
