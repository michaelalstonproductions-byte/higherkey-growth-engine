from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import utc_now
from .runtime_db import connect, migrate, upsert_record


def event_log_path(config: AppConfig) -> Path:
    return config.analytics_dir / "events.jsonl"


def _event_id(timestamp: str, event_type: str, source: str, summary: dict[str, Any]) -> str:
    digest = hashlib.sha1()
    digest.update(timestamp.encode("utf-8"))
    digest.update(event_type.encode("utf-8"))
    digest.update(source.encode("utf-8"))
    digest.update(json.dumps(summary, sort_keys=True).encode("utf-8"))
    return f"evt_{digest.hexdigest()[:16]}"


def append_event(
    config: AppConfig,
    event_type: str,
    *,
    severity: str = "info",
    source: str = "runtime",
    related_ids: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = utc_now()
    summary_payload = summary or {}
    event = {
        "event_id": _event_id(timestamp, event_type, source, summary_payload),
        "timestamp": timestamp,
        "type": event_type,
        "severity": severity,
        "source": source,
        "project_root": str(config.root),
        "related_ids": related_ids or {},
        "summary": summary_payload,
        "metadata": metadata or {},
        "local_only": True,
    }
    path = event_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    try:
        with connect(config) as connection:
            migrate(connection)
            upsert_record(
                connection,
                "events",
                record_id=event["event_id"],
                project_id=str(config.root),
                type=event_type,
                status="recorded",
                severity=severity,
                source=source,
                related_id=json.dumps(related_ids or {}, sort_keys=True),
                summary=summary_payload,
                metadata=event,
                created_at=timestamp,
                updated_at=timestamp,
            )
            connection.commit()
    except Exception:
        # JSONL is the source of truth for append-only event durability.
        pass
    return event
