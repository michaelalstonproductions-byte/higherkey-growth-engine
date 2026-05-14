#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from growth_engine.observability import build_metrics
from growth_engine.runtime_db import connect, db_path, init_db, table_counts


def _entries(root: Path) -> list[dict[str, Any]]:
    return load_json_file(root / "queue" / "review_queue.json", {"entries": []}).get("entries", [])


def _is_test(entry: dict[str, Any]) -> bool:
    text = " ".join(str(entry.get(key, "")) for key in ("source_path", "clip_path", "clip_id", "id")).lower()
    return "smoke_sample" in text or "smoke" in text or "test" in text or "colorbar" in text


def _status_label(pipeline: dict[str, Any], production_count: int) -> tuple[str, str]:
    raw = str(pipeline.get("severity") or pipeline.get("status") or pipeline.get("state") or "unknown").lower()
    if raw in {"fail", "failed"} and production_count:
        return "needs_attention", "Older missing media references were skipped. Clips are ready."
    if raw in {"needs_attention", "warn", "warning"}:
        return "needs_attention", pipeline.get("message") or "Pipeline needs attention."
    if production_count:
        return "ready", "Pipeline ready. Clips are available."
    return "empty", "Import footage to begin."


def build_snapshot(root: Path) -> dict[str, Any]:
    config = load_config(root)
    init_db(config)
    entries = _entries(config.root)
    production_entries = [entry for entry in entries if not _is_test(entry)]
    approved = [entry for entry in production_entries if entry.get("status") == "approved"]
    hidden_test_media = len(entries) - len(production_entries)
    pipeline = load_json_file(config.analytics_dir / "pipeline_status.json", {})
    diagnostics = load_json_file(config.analytics_dir / "diagnostics.json", {})
    qa = load_json_file(config.analytics_dir / "qa_report.json", {})
    recommendations = load_json_file(config.analytics_dir / "recommendations.json", {})
    social_manifest = load_json_file(config.root / "out" / "social_exports" / "manifest.json", {})
    repair = load_json_file(config.analytics_dir / "project_repair_report.json", {})
    validation = load_json_file(config.analytics_dir / "project_validation_report.json", {})
    size_report = load_json_file(config.analytics_dir / "project_size_report.json", {})
    backup_report = load_json_file(config.analytics_dir / "project_backup_report.json", {})
    restore_report = load_json_file(config.analytics_dir / "project_restore_report.json", {})
    security_report = load_json_file(config.analytics_dir / "security_report.json", {})
    client_storage = load_json_file(config.analytics_dir / "client_storage.json", {})
    manifest = load_json_file(config.root / "config" / "project_manifest.json", {})
    metrics = build_metrics(config)
    status, message = _status_label(pipeline, len(production_entries))
    best = max(production_entries, key=lambda item: int(item.get("score") or 0), default=None)

    with connect(config) as connection:
        counts = table_counts(connection)

    warnings = []
    if repair.get("counts", {}).get("missing_sources") or repair.get("counts", {}).get("stale_queue_entries"):
        warnings.append("Older missing media references were skipped.")
    if diagnostics.get("status") in {"warn", "fail"}:
        warnings.append("Diagnostics need attention.")
    if qa.get("status") in {"warn", "fail"}:
        warnings.append("QA has warnings.")

    runtime_snapshot = {
        "version": 1,
        "updated_at": utc_now(),
        "project_root": str(config.root),
        "runtime_db": str(db_path(config)),
        "db_counts": counts,
        "project_manifest": manifest,
        "pipeline_status": pipeline,
        "diagnostics": diagnostics,
        "qa_report": qa,
        "repair_report": repair,
        "project_validation": validation,
        "project_size_report": size_report,
        "project_backup_report": backup_report,
        "project_restore_report": restore_report,
        "security_report": security_report,
        "client_storage": client_storage,
        "queue_count": len(entries),
        "production_clip_count": len(production_entries),
        "hidden_test_media_count": hidden_test_media,
        "social_exports": social_manifest,
        "local_only": True,
    }
    client_state = {
        "version": 1,
        "last_updated": runtime_snapshot["updated_at"],
        "local_only": True,
        "project_status": "active",
        "project_name": manifest.get("project_name") or config.root.name,
        "total_production_clips": len(production_entries),
        "approved_clips": len(approved),
        "ready_social_exports": social_manifest.get("count", 0),
        "pipeline_status": status,
        "pipeline_message": message,
        "latest_recommendation": (recommendations.get("recommendations") or [{}])[0].get("reason") if recommendations.get("recommendations") else None,
        "best_clip": {"clip_id": best.get("clip_id"), "score": best.get("score")} if best else None,
        "health_status": "healthy" if diagnostics.get("status") == "pass" and status == "ready" else ("needs_attention" if status != "empty" else "ready_to_import"),
        "next_action": "Import Footage" if not production_entries else ("Review Clips" if not approved else "Export Social Packs"),
        "warnings_summary": warnings,
        "hidden_test_media_count": hidden_test_media,
        "project_validated": validation.get("status") == "pass",
        "latest_backup": None if backup_report.get("dry_run") else backup_report.get("backup_path"),
        "latest_restore": restore_report.get("target") or restore_report.get("backup_path"),
        "project_size_summary": {
            "total_size_bytes": size_report.get("total_size_bytes", 0),
            "content_inbox_size_bytes": (size_report.get("sizes") or {}).get("content_inbox", 0),
            "clips_size_bytes": (size_report.get("sizes") or {}).get("clips", 0),
            "backups_size_bytes": (size_report.get("sizes") or {}).get("backups", 0),
        },
        "cleanup_recommendation": (size_report.get("cleanup_suggestions") or ["Run project size report."])[0],
        "demo_reset_available": True,
        "health_score": metrics.get("health_score"),
        "health_label": metrics.get("health_label"),
        "security_status": security_report.get("label", "Unknown"),
        "security_summary": {
            "status": security_report.get("status", "unknown"),
            "label": security_report.get("label", "Unknown"),
        },
        "storage_status": client_storage.get("label", "Unknown"),
        "storage_summary": {
            "status": client_storage.get("status", "unknown"),
            "label": client_storage.get("label", "Unknown"),
            "generated_size_mb": client_storage.get("generated_size_mb", 0),
            "cleanup_candidate_count": client_storage.get("cleanup_candidate_count", 0),
        },
    }
    save_json_file(config.analytics_dir / "runtime_snapshot.json", runtime_snapshot)
    save_json_file(config.analytics_dir / "client_state.json", client_state)
    append_event(config, "diagnostics.completed", severity="info", source="build_runtime_snapshot", summary={"client_state": client_state})
    return {"runtime_snapshot": runtime_snapshot, "client_state": client_state}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build runtime and client state snapshots.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    result = build_snapshot(Path(args.root).resolve())
    print(json.dumps({
        "status": "pass",
        "runtime_snapshot": "analytics/runtime_snapshot.json",
        "client_state": "analytics/client_state.json",
        "client_summary": result["client_state"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
