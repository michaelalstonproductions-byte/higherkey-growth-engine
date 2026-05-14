from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit import audit_summary, read_recent_audit_events, write_audit_event
from .config import AppConfig
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .runtime_db import connect, db_path, init_db


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _entries(config: AppConfig) -> list[dict[str, Any]]:
    queue = load_json_file(config.queue_path, {"entries": []})
    return queue.get("entries", []) if isinstance(queue, dict) else []


def _is_test(entry: dict[str, Any]) -> bool:
    text = " ".join(str(entry.get(key, "")) for key in ("source_path", "clip_path", "clip_id", "id", "filename")).lower()
    return any(token in text for token in ("smoke", "testsrc", "test", "colorbar", "color_bar"))


def _status(path: Path) -> str:
    payload = load_json_file(path, {})
    return str(payload.get("status") or payload.get("state") or "unknown").lower()


def _task_counts(config: AppConfig) -> dict[str, int]:
    try:
        with connect(config) as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM task_queue GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}
    except Exception:
        return {}


def _recent_issues(config: AppConfig) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for source, path in (
        ("qa", config.analytics_dir / "qa_report.json"),
        ("diagnostics", config.analytics_dir / "diagnostics.json"),
        ("pipeline", config.analytics_dir / "pipeline_status.json"),
        ("repair", config.analytics_dir / "project_repair_report.json"),
        ("worker", config.analytics_dir / "worker_runtime_status.json"),
    ):
        payload = load_json_file(path, {})
        status = str(payload.get("status") or payload.get("state") or "").lower()
        if status in {"warn", "fail", "failed", "needs_attention", "stale"}:
            issues.append({
                "source": source,
                "status": status,
                "message": payload.get("message") or payload.get("client_message") or f"{source} needs attention",
            })
    return issues[:20]


def health_score(metrics: dict[str, Any]) -> int:
    score = 100
    diagnostics = metrics.get("diagnostics", {})
    if diagnostics.get("status") == "warn":
        score -= 10
    if diagnostics.get("status") == "fail":
        score -= 30
    if metrics.get("media", {}).get("production_clips", 0) == 0:
        score -= 20
    missing = int(metrics.get("media", {}).get("missing_media_count", 0) or 0)
    if missing:
        score -= min(25, 5 + missing)
    task_counts = metrics.get("tasks", {}).get("counts", {})
    failed_tasks = int(task_counts.get("failed", 0) or 0)
    if failed_tasks:
        score -= min(20, failed_tasks * 3)
    worker_state = str(metrics.get("worker", {}).get("state") or "").lower()
    if worker_state in {"failed", "stale"}:
        score -= 15
    api_state = str(metrics.get("local_api", {}).get("state") or "").lower()
    if api_state in {"failed", "error"}:
        score -= 10
    validation_status = str(metrics.get("project", {}).get("validation_status") or "").lower()
    if validation_status == "fail":
        score -= 25
    if validation_status == "warn":
        score -= 10
    security_status = str(metrics.get("security", {}).get("status") or "").lower()
    if security_status == "fail":
        score -= 25
    if security_status == "warn":
        score -= 10
    storage_status = str(metrics.get("storage", {}).get("status") or "").lower()
    if storage_status == "fail":
        score -= 10
    if storage_status == "warn":
        score -= 5
    return max(0, min(100, score))


def client_health_label(score: int) -> str:
    if score >= 85:
        return "Healthy"
    if score >= 65:
        return "Needs Attention"
    if score >= 40:
        return "Degraded"
    return "Failed"


def build_metrics(config: AppConfig) -> dict[str, Any]:
    init_db(config)
    entries = _entries(config)
    production = [entry for entry in entries if not _is_test(entry)]
    approved = [entry for entry in production if str(entry.get("status") or entry.get("decision") or "").lower() == "approved"]
    diagnostics = load_json_file(config.analytics_dir / "diagnostics.json", {})
    qa = load_json_file(config.analytics_dir / "qa_report.json", {})
    repair = load_json_file(config.analytics_dir / "project_repair_report.json", {})
    pipeline = load_json_file(config.analytics_dir / "pipeline_status.json", {})
    worker = load_json_file(config.analytics_dir / "worker_runtime_status.json", {})
    local_api = load_json_file(config.analytics_dir / "local_api_status.json", {})
    security = load_json_file(config.analytics_dir / "security_report.json", {})
    storage = load_json_file(config.analytics_dir / "client_storage.json", {})
    validation = load_json_file(config.analytics_dir / "project_validation_report.json", {})
    size_report = load_json_file(config.analytics_dir / "project_size_report.json", {})
    social_history = load_json_file(config.analytics_dir / "social_export_history.json", {})
    social_manifest = load_json_file(config.root / "out" / "social_exports" / "manifest.json", {})
    color = load_json_file(config.analytics_dir / "color_school_report.json", {})
    audio = load_json_file(config.analytics_dir / "audio_school_report.json", {})
    task_counts = _task_counts(config)
    db_file = db_path(config)
    metrics = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "tasks": {
            "counts": task_counts,
            "queued": task_counts.get("queued", 0) + task_counts.get("scheduled", 0),
            "running": task_counts.get("running", 0),
            "failed": task_counts.get("failed", 0),
        },
        "worker": {
            "state": worker.get("state", "unknown"),
            "status": worker.get("status", worker.get("state", "unknown")),
            "pid": worker.get("pid"),
            "started_at": worker.get("started_at"),
            "heartbeat_at": worker.get("heartbeat_at"),
        },
        "pipeline": {
            "status": pipeline.get("status", "unknown"),
            "severity": pipeline.get("severity", pipeline.get("status", "unknown")),
            "run_count": _jsonl_count(config.analytics_dir / "events.jsonl"),
            "stage_counts": {
                "pass": 1 if pipeline.get("status") == "pass" else 0,
                "warn": 1 if pipeline.get("status") in {"warn", "needs_attention"} else 0,
                "fail": 1 if pipeline.get("status") in {"fail", "failed"} else 0,
            },
        },
        "media": {
            "queue_count": len(entries),
            "production_clips": len(production),
            "approved_clips": len(approved),
            "hidden_test_media_count": len(entries) - len(production),
            "missing_media_count": (repair.get("counts") or {}).get("missing_sources", 0),
            "stale_queue_entries": (repair.get("counts") or {}).get("stale_queue_entries", 0),
        },
        "repair": {
            "status": repair.get("status", "unknown"),
            "counts": repair.get("counts", {}),
        },
        "social_exports": {
            "history_count": len(social_history.get("history", [])) if isinstance(social_history, dict) else 0,
            "ready_count": social_manifest.get("count", 0) if isinstance(social_manifest, dict) else 0,
            "status": social_manifest.get("status", "unknown") if isinstance(social_manifest, dict) else "unknown",
        },
        "schools": {
            "color_status": color.get("status", "unknown"),
            "audio_status": audio.get("status", "unknown"),
            "color_updated_at": color.get("updated_at"),
            "audio_updated_at": audio.get("updated_at"),
        },
        "diagnostics": {
            "status": diagnostics.get("status", "unknown"),
            "qa_status": qa.get("status", "unknown"),
        },
        "runtime": {
            "db_path": str(db_file),
            "db_size_bytes": db_file.stat().st_size if db_file.exists() else 0,
            "project_size_bytes": size_report.get("total_size_bytes") or _dir_size(config.root),
            "events_count": _jsonl_count(config.analytics_dir / "events.jsonl"),
            "audit_events_count": _jsonl_count(config.analytics_dir / "audit_log.jsonl"),
        },
        "project": {
            "validation_status": validation.get("status", "unknown"),
            "cleanup_recommendation": (size_report.get("cleanup_suggestions") or ["Run project size report."])[0],
        },
        "local_api": {
            "state": local_api.get("state", "unknown"),
            "port": local_api.get("port"),
        },
        "security": {
            "status": security.get("status", "unknown"),
            "label": security.get("label", "Needs Attention" if security else "Unknown"),
            "policy_version": (security.get("policy_summary") or {}).get("version"),
        },
        "storage": {
            "status": storage.get("status", "unknown"),
            "label": storage.get("label", "Unknown"),
            "generated_size_mb": storage.get("generated_size_mb", 0),
            "cleanup_candidate_count": storage.get("cleanup_candidate_count", 0),
        },
        "latest_issues": _recent_issues(config),
    }
    score = health_score(metrics)
    metrics["health_score"] = score
    metrics["health_label"] = client_health_label(score)
    return metrics


def build_client_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    score = int(metrics.get("health_score", 0))
    label = client_health_label(score)
    media = metrics.get("media", {})
    tasks = metrics.get("tasks", {})
    issues = metrics.get("latest_issues", [])
    return {
        "version": 1,
        "updated_at": metrics.get("updated_at") or utc_now(),
        "local_only": True,
        "health_score": score,
        "health_label": label,
        "runtime_status": "Ready" if score >= 85 else ("Needs Attention" if score >= 65 else "Failed"),
        "media_summary": {
            "production_clips": media.get("production_clips", 0),
            "approved_clips": media.get("approved_clips", 0),
            "missing_media": media.get("missing_media_count", 0),
        },
        "task_summary": {
            "queued": tasks.get("queued", 0),
            "running": tasks.get("running", 0),
            "failed": tasks.get("failed", 0),
        },
        "worker_status": metrics.get("worker", {}).get("state", "unknown"),
        "pipeline_status": metrics.get("pipeline", {}).get("status", "unknown"),
        "security_status": metrics.get("security", {}).get("label", "Unknown"),
        "storage_status": metrics.get("storage", {}).get("label", "Unknown"),
        "school_status": metrics.get("schools", {}),
        "next_action": "Review Clips" if media.get("production_clips", 0) else "Import Footage",
        "warnings": [issue.get("message", "Needs attention") for issue in issues[:5]],
    }


def write_metrics(config: AppConfig) -> dict[str, Any]:
    metrics = build_metrics(config)
    client = build_client_metrics(metrics)
    save_json_file(config.analytics_dir / "runtime_metrics.json", metrics)
    save_json_file(config.analytics_dir / "client_metrics.json", client)
    append_event(config, "diagnostics.completed", severity="info", source="observability", summary={"health_score": metrics["health_score"]})
    return {"runtime_metrics": metrics, "client_metrics": client}


def build_observability_report(config: AppConfig) -> dict[str, Any]:
    payload = write_metrics(config)
    events = []
    event_path = config.analytics_dir / "events.jsonl"
    if event_path.exists():
        for line in event_path.read_text(encoding="utf-8").splitlines()[-100:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "runtime_metrics": payload["runtime_metrics"],
        "audit_summary": audit_summary(config),
        "recent_audit_events": read_recent_audit_events(config, limit=50),
        "recent_events": events,
        "task_worker_history": load_json_file(config.analytics_dir / "task_worker_history.json", {}),
        "worker_runtime_history": load_json_file(config.analytics_dir / "worker_runtime_history.json", {}),
        "maintenance_report": load_json_file(config.analytics_dir / "maintenance_report.json", {}),
        "qa_report": load_json_file(config.analytics_dir / "qa_report.json", {}),
        "project_repair_report": load_json_file(config.analytics_dir / "project_repair_report.json", {}),
        "pipeline_status": load_json_file(config.analytics_dir / "pipeline_status.json", {}),
    }
    client = {
        "version": 1,
        "updated_at": report["updated_at"],
        "local_only": True,
        "health_score": payload["client_metrics"]["health_score"],
        "health_label": payload["client_metrics"]["health_label"],
        "runtime_status": payload["client_metrics"]["runtime_status"],
        "storage_status": payload["client_metrics"].get("storage_status", "Unknown"),
        "latest_warnings": payload["client_metrics"]["warnings"],
        "recent_activity": [
            {
                "type": event.get("type"),
                "severity": event.get("severity"),
                "summary": event.get("summary", {}),
                "timestamp": event.get("timestamp"),
            }
            for event in events[-20:]
        ],
        "audit_count": report["audit_summary"]["recent_count"],
    }
    save_json_file(config.analytics_dir / "observability_report.json", report)
    save_json_file(config.analytics_dir / "client_observability.json", client)
    write_audit_event(config, "diagnostics.run", source="observability", summary={"health_score": payload["client_metrics"]["health_score"]})
    return {"observability_report": report, "client_observability": client}
