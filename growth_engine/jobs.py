from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import AppConfig, ensure_directories
from .index import file_fingerprint, relative_path, utc_now
from .ingest import discover_videos
from .pipeline import process_once


JOB_STATES = {"queued", "processing", "completed", "failed", "retrying"}


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def job_paths(config: AppConfig) -> dict[str, Path]:
    return {
        "jobs": config.analytics_dir / "jobs.json",
        "history": config.analytics_dir / "job_history.json",
        "status": config.analytics_dir / "pipeline_status.json",
        "activity": config.analytics_dir / "activity_feed.json",
        "api": config.analytics_dir / "local_api_contract.json",
        "retry": config.queue_dir / "reprocess_requests.json",
    }


def load_jobs(config: AppConfig) -> dict[str, Any]:
    return _read(job_paths(config)["jobs"], {"version": 1, "jobs": []})


def save_jobs(config: AppConfig, jobs: dict[str, Any]) -> None:
    jobs["updated_at"] = utc_now()
    _write(job_paths(config)["jobs"], jobs)


def append_activity(config: AppConfig, event: str, message: str, job: dict[str, Any] | None = None) -> None:
    path = job_paths(config)["activity"]
    feed = _read(path, {"version": 1, "events": []})
    feed.setdefault("events", []).append(
        {
            "at": utc_now(),
            "event": event,
            "message": message,
            "job_id": job.get("id") if job else None,
            "source_path": job.get("source_path") if job else None,
        }
    )
    feed["events"] = feed["events"][-200:]
    feed["updated_at"] = utc_now()
    _write(path, feed)


def write_status(config: AppConfig, state: str, message: str, active_job: dict[str, Any] | None = None) -> None:
    jobs = load_jobs(config).get("jobs", [])
    counts = {status: sum(1 for job in jobs if job.get("state") == status) for status in sorted(JOB_STATES)}
    payload = {
        "updated_at": utc_now(),
        "state": state,
        "message": message,
        "active_job_id": active_job.get("id") if active_job else None,
        "counts": counts,
        "local_only": True,
    }
    _write(job_paths(config)["status"], payload)


def append_history(config: AppConfig, job: dict[str, Any]) -> None:
    path = job_paths(config)["history"]
    history = _read(path, {"version": 1, "jobs": []})
    history.setdefault("jobs", []).append(job.copy())
    history["jobs"] = history["jobs"][-500:]
    history["updated_at"] = utc_now()
    _write(path, history)


def _known_sources(jobs: dict[str, Any]) -> set[str]:
    return {job.get("source_path", "") for job in jobs.get("jobs", []) if job.get("source_path")}


def enqueue_new_videos(config: AppConfig) -> int:
    ensure_directories(config)
    jobs = load_jobs(config)
    known = _known_sources(jobs)
    added = 0
    for video_path in discover_videos(config.inbox_dir):
        source = relative_path(video_path, config.root)
        if source in known:
            continue
        job = {
            "id": f"job_{file_fingerprint(video_path)}",
            "state": "queued",
            "source_path": source,
            "video_id": file_fingerprint(video_path),
            "attempts": 0,
            "max_attempts": 3,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "last_error": None,
            "summary": None,
        }
        jobs.setdefault("jobs", []).append(job)
        known.add(source)
        added += 1
        append_activity(config, "queued", f"Queued {source}", job)
    save_jobs(config, jobs)
    write_status(config, "idle", f"Queued {added} new video(s)")
    return added


def apply_retry_requests(config: AppConfig, retry_failed: bool = False) -> int:
    paths = job_paths(config)
    jobs = load_jobs(config)
    requests = _read(paths["retry"], {"requests": []})
    requested = {item.get("job_id") or item.get("video_id") or item.get("source_path") for item in requests.get("requests", []) if isinstance(item, dict)}
    changed = 0
    for job in jobs.get("jobs", []):
        should_retry = retry_failed and job.get("state") == "failed"
        should_retry = should_retry or job.get("id") in requested or job.get("video_id") in requested or job.get("source_path") in requested
        if should_retry:
            job["state"] = "retrying"
            job["updated_at"] = utc_now()
            job["last_error"] = None
            changed += 1
            append_activity(config, "retrying", f"Retry requested for {job['source_path']}", job)
    if requests.get("requests"):
        _write(paths["retry"], {"version": 1, "requests": [], "updated_at": utc_now()})
    save_jobs(config, jobs)
    return changed


def process_next_job(config: AppConfig) -> dict[str, Any] | None:
    jobs = load_jobs(config)
    next_job = next((job for job in jobs.get("jobs", []) if job.get("state") in {"queued", "retrying"}), None)
    if not next_job:
        write_status(config, "idle", "No queued jobs")
        return None
    next_job["state"] = "processing"
    next_job["attempts"] = int(next_job.get("attempts", 0)) + 1
    next_job["started_at"] = utc_now()
    next_job["updated_at"] = utc_now()
    save_jobs(config, jobs)
    write_status(config, "processing", f"Processing {next_job['source_path']}", next_job)
    append_activity(config, "processing", f"Started {next_job['source_path']}", next_job)

    try:
        summary = process_once(config)
        if summary.get("errors"):
            raise RuntimeError(summary["errors"][0].get("error", "pipeline error"))
        next_job["state"] = "completed"
        next_job["completed_at"] = utc_now()
        next_job["summary"] = summary
        append_activity(config, "completed", f"Completed {next_job['source_path']}", next_job)
    except Exception as exc:  # noqa: BLE001 - daemon must persist failures instead of crashing.
        next_job["last_error"] = str(exc)
        if next_job["attempts"] < next_job.get("max_attempts", 3):
            next_job["state"] = "retrying"
            append_activity(config, "retrying", f"Retrying {next_job['source_path']}: {exc}", next_job)
        else:
            next_job["state"] = "failed"
            append_activity(config, "failed", f"Failed {next_job['source_path']}: {exc}", next_job)
    next_job["updated_at"] = utc_now()
    save_jobs(config, jobs)
    append_history(config, next_job)
    write_status(config, next_job["state"], f"Job {next_job['state']}: {next_job['source_path']}", next_job)
    return next_job


def write_api_contract(config: AppConfig) -> None:
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "description": "Placeholder contract for future desktop/mobile wrapper.",
        "resources": {
            "pipeline_status": relative_path(job_paths(config)["status"], config.root),
            "jobs": relative_path(job_paths(config)["jobs"], config.root),
            "job_history": relative_path(job_paths(config)["history"], config.root),
            "activity_feed": relative_path(job_paths(config)["activity"], config.root),
            "review_queue": relative_path(config.queue_path, config.root),
        },
        "future_endpoints": [
            "GET /status",
            "GET /jobs",
            "POST /jobs/retry",
            "GET /activity",
        ],
    }
    _write(job_paths(config)["api"], payload)


def daemon_tick(config: AppConfig, retry_failed: bool = False) -> dict[str, Any]:
    write_api_contract(config)
    queued = enqueue_new_videos(config)
    retries = apply_retry_requests(config, retry_failed=retry_failed)
    job = process_next_job(config)
    return {"queued": queued, "retry_requests": retries, "processed_job": job}


def run_daemon(config: AppConfig, interval_seconds: float = 5.0, once: bool = False, retry_failed: bool = False) -> None:
    write_status(config, "starting", "Watcher daemon starting")
    append_activity(config, "daemon_started", "Watcher daemon started")
    while True:
        daemon_tick(config, retry_failed=retry_failed)
        if once:
            break
        time.sleep(interval_seconds)
