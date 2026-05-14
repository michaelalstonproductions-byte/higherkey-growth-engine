#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.events import append_event
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.runtime_db import connect, db_path, migrate, table_counts, upsert_record


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def backfill(root: Path, *, quick: bool = False) -> dict[str, Any]:
    config = load_config(root)
    project_id = str(config.root)
    inserted = {name: 0 for name in (
        "projects",
        "media_assets",
        "clips",
        "jobs",
        "packages",
        "social_exports",
        "diagnostics",
        "school_reports",
        "pipeline_runs",
        "agent_runs",
    )}
    now = utc_now()

    with connect(config) as connection:
        migrate(connection)
        upsert_record(
            connection,
            "projects",
            record_id=project_id,
            project_id=project_id,
            type="project",
            status="active",
            path=str(config.root),
            summary={"root": str(config.root), "content_inbox": str(config.inbox_dir)},
            metadata=load_json_file(config.root / "config" / "project_manifest.json", {}),
            created_at=now,
            updated_at=now,
        )
        inserted["projects"] += 1

        index = load_json_file(config.index_path, {"videos": {}})
        for video in index.get("videos", {}).values():
            upsert_record(
                connection,
                "media_assets",
                record_id=str(video.get("id") or stable_id("media", video)),
                project_id=project_id,
                type="video",
                status=video.get("status"),
                severity="warn" if video.get("status") == "missing_source" else "info",
                source="video_index",
                path=video.get("source_path"),
                summary={"filename": video.get("filename"), "clips": len(video.get("clips", []))},
                metadata=video,
                created_at=video.get("registered_at") or now,
                updated_at=video.get("updated_at") or now,
            )
            inserted["media_assets"] += 1
            for clip in video.get("clips", []):
                upsert_record(
                    connection,
                    "clips",
                    record_id=str(clip.get("id") or stable_id("clip", clip)),
                    project_id=project_id,
                    type="clip",
                    status=clip.get("status") or "ready",
                    severity="info",
                    source="video_index",
                    path=clip.get("path"),
                    related_id=video.get("id"),
                    summary={"score": clip.get("score"), "duration": clip.get("duration_seconds")},
                    metadata=clip,
                    created_at=video.get("registered_at") or now,
                    updated_at=clip.get("updated_at") or video.get("updated_at") or now,
                )
                inserted["clips"] += 1
            for package in video.get("packages", []):
                upsert_record(
                    connection,
                    "packages",
                    record_id=str(package.get("id") or stable_id("package", package)),
                    project_id=project_id,
                    type="caption_package",
                    status="ready",
                    source="video_index",
                    path=package.get("path"),
                    related_id=package.get("clip_id") or video.get("id"),
                    summary={"clip_id": package.get("clip_id"), "title": package.get("title")},
                    metadata=package,
                    created_at=video.get("registered_at") or now,
                    updated_at=video.get("updated_at") or now,
                )
                inserted["packages"] += 1

        queue = load_json_file(config.queue_path, {"entries": []})
        for entry in queue.get("entries", []):
            upsert_record(
                connection,
                "clips",
                record_id=str(entry.get("clip_id") or entry.get("id") or stable_id("queue_clip", entry)),
                project_id=project_id,
                type="queue_entry",
                status=entry.get("status") or "needs_review",
                severity="info",
                source="review_queue",
                path=entry.get("clip_path"),
                related_id=entry.get("source_video_id"),
                summary={"queue_id": entry.get("id"), "score": entry.get("score")},
                metadata=entry,
                updated_at=queue.get("updated_at") or now,
            )

        for filename, table, record_type in (
            ("jobs.json", "jobs", "job"),
            ("job_history.json", "jobs", "job_history"),
        ):
            payload = load_json_file(config.analytics_dir / filename, {"jobs": []})
            for job in payload.get("jobs", []):
                upsert_record(
                    connection,
                    table,
                    record_id=str(job.get("id") or stable_id("job", job)),
                    project_id=project_id,
                    type=record_type,
                    status=job.get("state"),
                    severity="fail" if job.get("state") == "failed" else "info",
                    source=filename,
                    path=job.get("source_path"),
                    related_id=job.get("video_id"),
                    summary={"attempts": job.get("attempts"), "last_error": job.get("last_error")},
                    metadata=job,
                    created_at=job.get("created_at") or now,
                    updated_at=job.get("updated_at") or now,
                )
                inserted["jobs"] += 1

        for filename, table, record_type in (
            ("diagnostics.json", "diagnostics", "diagnostics"),
            ("qa_report.json", "diagnostics", "qa_report"),
            ("pipeline_status.json", "pipeline_runs", "pipeline_status"),
            ("media_cache.json", "diagnostics", "media_cache"),
        ):
            payload = load_json_file(config.analytics_dir / filename, {})
            if payload:
                upsert_record(
                    connection,
                    table,
                    record_id=f"{record_type}_{filename}",
                    project_id=project_id,
                    type=record_type,
                    status=payload.get("status") or payload.get("state"),
                    severity=payload.get("severity") or payload.get("status"),
                    source=filename,
                    path=rel(config.analytics_dir / filename, config.root),
                    summary={key: payload.get(key) for key in ("status", "state", "count", "updated_at") if key in payload},
                    metadata=payload,
                    updated_at=payload.get("updated_at") or now,
                )
                inserted[table] += 1

        for filename, school in (
            ("color_school_report.json", "color_school"),
            ("audio_school_report.json", "audio_school"),
        ):
            payload = load_json_file(config.analytics_dir / filename, {})
            if payload:
                upsert_record(
                    connection,
                    "school_reports",
                    record_id=school,
                    project_id=project_id,
                    type=school,
                    status=payload.get("status"),
                    severity=payload.get("status"),
                    source=filename,
                    path=rel(config.analytics_dir / filename, config.root),
                    summary=payload.get("summary", {}),
                    metadata=payload,
                    updated_at=payload.get("updated_at") or now,
                )
                inserted["school_reports"] += 1

        agents = load_json_file(config.analytics_dir / "agents.json", {"agents": []})
        for agent in agents.get("agents", []):
            upsert_record(
                connection,
                "agent_runs",
                record_id=str(agent.get("id") or agent.get("agent_id") or stable_id("agent", agent)),
                project_id=project_id,
                type="agent",
                status=agent.get("state"),
                severity="fail" if agent.get("state") == "failed" else "info",
                source="agents.json",
                summary={"name": agent.get("name"), "state": agent.get("state")},
                metadata=agent,
                updated_at=agent.get("updated_at") or now,
            )
            inserted["agent_runs"] += 1
        activity = load_json_file(config.analytics_dir / "agent_activity.json", {"events": []})
        for event in activity.get("events", [])[-50 if quick else None:]:
            upsert_record(
                connection,
                "agent_runs",
                record_id=str(event.get("id") or stable_id("agent_event", event)),
                project_id=project_id,
                type="agent_activity",
                status=event.get("state") or event.get("status"),
                source="agent_activity.json",
                summary={"event": event.get("event") or event.get("message")},
                metadata=event,
                updated_at=event.get("updated_at") or event.get("at") or now,
            )
            inserted["agent_runs"] += 1

        for path in (config.root / "out" / "social_exports" / "manifest.json", config.analytics_dir / "social_export_history.json"):
            payload = load_json_file(path, {})
            if payload:
                upsert_record(
                    connection,
                    "social_exports",
                    record_id=path.stem,
                    project_id=project_id,
                    type=path.stem,
                    status=payload.get("status") or "ready",
                    severity="info",
                    source=rel(path, config.root),
                    path=rel(path, config.root),
                    summary={key: payload.get(key) for key in ("count", "updated_at", "output_dir") if key in payload},
                    metadata=payload,
                    updated_at=payload.get("updated_at") or now,
                )
                inserted["social_exports"] += 1
        connection.commit()
        counts = table_counts(connection)

    event = append_event(config, "qa.completed" if quick else "repair.completed", severity="info", source="backfill_runtime_db", summary={"inserted": inserted})
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "quick": quick,
        "runtime_db": str(db_path(config)),
        "inserted": inserted,
        "table_counts": counts,
        "event_id": event["event_id"],
        "local_only": True,
    }
    save_json_file(config.analytics_dir / "runtime_backfill_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill HigherKey runtime SQLite DB from existing JSON snapshots.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--quick", action="store_true", help="Limit activity/event ingestion for QA.")
    args = parser.parse_args()
    report = backfill(Path(args.root).resolve(), quick=args.quick)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
