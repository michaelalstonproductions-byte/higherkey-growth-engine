from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig, ensure_directories
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .runtime_db import SCHEMA_VERSION, connect, db_path, init_db, table_counts


REPORT = "state_reconciliation_report.json"
CLIENT_INTEGRITY = "client_integrity.json"
QUARANTINE_REPORT = "quarantine_report.json"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load_json_any(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"
    except OSError as exc:
        return None, f"unreadable: {exc}"


def _queue_entries(config: AppConfig) -> list[dict[str, Any]]:
    data = load_json_file(config.queue_path, {"entries": []})
    return data.get("entries", []) if isinstance(data, dict) else []


def _entry_id(entry: dict[str, Any]) -> str:
    return str(entry.get("clip_id") or entry.get("id") or entry.get("clip_path") or entry.get("filename") or "")


def _entry_paths(entry: dict[str, Any], config: AppConfig) -> list[tuple[str, Path]]:
    paths = []
    for key in ("clip_path", "caption_path", "package_path", "thumbnail_path"):
        value = entry.get(key)
        if value:
            paths.append((key, (config.root / str(value)).resolve() if not Path(str(value)).is_absolute() else Path(str(value))))
    return paths


def _file_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and ("/" in item or item.endswith((".json", ".txt", ".mp4", ".mov", ".m4v", ".jpg", ".png"))):
                refs.append(item)
            else:
                refs.extend(_file_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_file_refs(item))
    return refs


def _issue(kind: str, severity: str, message: str, *, path: str | None = None, item_id: str | None = None, repairable: bool = False) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "message": message,
        "path": path,
        "id": item_id,
        "repairable": repairable,
    }


def _db_ids(config: AppConfig, table: str) -> set[str]:
    try:
        with connect(config) as connection:
            rows = connection.execute(f"SELECT id FROM {table}").fetchall()
        return {str(row["id"]) for row in rows}
    except Exception:
        return set()


def _schema_versions(config: AppConfig) -> list[int]:
    try:
        with connect(config) as connection:
            rows = connection.execute("SELECT version FROM schema_version").fetchall()
        return [int(row["version"]) for row in rows]
    except Exception:
        return []


def _check_runtime_db(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    init_db(config)
    versions = _schema_versions(config)
    if SCHEMA_VERSION not in versions:
        issues.append(_issue("runtime_db_schema", "fail", f"Runtime DB schema version {SCHEMA_VERSION} not recorded.", path=_rel(db_path(config), config.root), repairable=True))
    try:
        with connect(config) as connection:
            counts = table_counts(connection)
    except Exception as exc:
        counts = {}
        issues.append(_issue("runtime_db_unreadable", "fail", f"Runtime DB unreadable: {exc}", path=_rel(db_path(config), config.root)))
    return issues, {"schema_versions": versions, "table_counts": counts}


def _check_json_files(config: AppConfig, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for rel in contract.get("required_runtime_files", []) + contract.get("client_facing_files", []) + contract.get("snapshots", []):
        path = config.root / rel
        data, error = _load_json_any(path) if path.suffix == ".json" else (None, None)
        if not path.exists() and rel in contract.get("required_runtime_files", []):
            issues.append(_issue("missing_required_file", "fail", "Required runtime file is missing.", path=rel, repairable=True))
        elif error and error != "missing":
            issues.append(_issue("invalid_json", "fail", error, path=rel))
    for rel in ("analytics/events.jsonl", "analytics/audit_log.jsonl"):
        path = config.root / rel
        if path.exists():
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    issues.append(_issue("invalid_jsonl", "fail", f"Invalid JSONL line {line_no}.", path=rel))
                    break
    return issues


def _check_queue(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    entries = _queue_entries(config)
    ids = [_entry_id(entry) for entry in entries if _entry_id(entry)]
    duplicates = [item for item, count in Counter(ids).items() if count > 1]
    for item_id in duplicates:
        issues.append(_issue("duplicate_clip_id", "warn", "Duplicate clip ID in review queue.", item_id=item_id, repairable=True))
    clip_db_ids = _db_ids(config, "clips")
    missing_db = [item_id for item_id in ids if item_id and item_id not in clip_db_ids]
    for item_id in missing_db[:100]:
        issues.append(_issue("missing_db_clip_row", "warn", "Queue clip missing from runtime DB clips table.", item_id=item_id, repairable=True))
    for entry in entries[:1000]:
        item_id = _entry_id(entry)
        for key, path in _entry_paths(entry, config):
            if key in {"clip_path", "caption_path", "package_path"} and not path.exists():
                issues.append(_issue(f"missing_{key}", "warn", f"Queue entry references missing {key}.", path=_rel(path, config.root), item_id=item_id, repairable=True))
    return issues, {"queue_entries": len(entries), "duplicate_clip_ids": len(duplicates), "missing_db_clip_rows": len(missing_db)}


def _check_media_cache(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = load_json_file(config.analytics_dir / "media_cache.json", {})
    assets = manifest.get("assets", []) if isinstance(manifest, dict) else []
    issues: list[dict[str, Any]] = []
    missing = 0
    for asset in assets[:1000]:
        for ref in _file_refs(asset):
            path = config.root / ref if not Path(ref).is_absolute() else Path(ref)
            if ("thumbnail" in ref or "strip" in ref or "media_cache" in ref) and not path.exists():
                missing += 1
                issues.append(_issue("missing_media_cache_file", "warn", "Media cache manifest references a missing file.", path=_rel(path, config.root), repairable=True))
    return issues, {"media_cache_assets": len(assets), "missing_cache_files": missing}


def _check_social_exports(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = load_json_file(config.root / "out" / "social_exports" / "manifest.json", {})
    refs = _file_refs(manifest)
    issues: list[dict[str, Any]] = []
    missing = 0
    for ref in refs[:1000]:
        path = config.root / ref if not Path(ref).is_absolute() else Path(ref)
        if ref.startswith("out/social_exports") and not path.exists():
            missing += 1
            issues.append(_issue("missing_social_export_file", "warn", "Social export manifest references a missing file.", path=_rel(path, config.root), repairable=True))
    return issues, {"social_export_refs": len(refs), "missing_social_export_files": missing}


def _check_schools(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queue_ids = {_entry_id(entry) for entry in _queue_entries(config)}
    issues: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for name in ("color_school_report.json", "audio_school_report.json"):
        data = load_json_file(config.analytics_dir / name, {})
        items = data.get("clips") or data.get("results") or []
        stale = 0
        for item in items[:1000] if isinstance(items, list) else []:
            clip_id = str(item.get("clip_id") or "")
            if clip_id and queue_ids and clip_id not in queue_ids:
                stale += 1
        if stale:
            issues.append(_issue("stale_school_report_clip", "warn", f"{name} contains clips not present in current queue.", path=f"analytics/{name}", repairable=True))
        summary[name] = {"items": len(items) if isinstance(items, list) else 0, "stale": stale}
    return issues, summary


def _check_tasks(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client_tasks = load_json_file(config.analytics_dir / "client_tasks.json", {})
    task_summary = load_json_file(config.analytics_dir / "task_summary.json", {})
    try:
        with connect(config) as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM task_queue GROUP BY status").fetchall()
        db_counts = {str(row["status"]): int(row["count"]) for row in rows}
    except Exception:
        db_counts = {}
    snapshot_counts = (task_summary.get("summary") or task_summary).get("counts", {}) if isinstance(task_summary, dict) else {}
    issues = []
    if db_counts and snapshot_counts:
        for status, count in db_counts.items():
            if int(snapshot_counts.get(status, 0) or 0) != count:
                issues.append(_issue("task_snapshot_mismatch", "warn", "Task summary snapshot differs from task_queue table.", item_id=status, repairable=True))
                break
    if not client_tasks:
        issues.append(_issue("client_tasks_missing", "warn", "client_tasks.json is missing or empty.", path="analytics/client_tasks.json", repairable=True))
    return issues, {"db_counts": db_counts, "snapshot_counts": snapshot_counts}


def _check_client_state(config: AppConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = load_json_file(config.analytics_dir / "client_state.json", {})
    runtime = load_json_file(config.analytics_dir / "runtime_snapshot.json", {})
    entries = _queue_entries(config)
    issues = []
    if client and int(client.get("total_production_clips", 0) or 0) > len(entries):
        issues.append(_issue("client_state_count_mismatch", "warn", "Client state clip count exceeds queue entries.", repairable=True))
    if not runtime:
        issues.append(_issue("runtime_snapshot_missing", "warn", "Runtime snapshot is missing or empty.", path="analytics/runtime_snapshot.json", repairable=True))
    return issues, {"client_state_present": bool(client), "runtime_snapshot_present": bool(runtime)}


def _build_client_integrity(report: dict[str, Any]) -> dict[str, Any]:
    severity = report.get("severity", "pass")
    if severity == "pass":
        label = "Healthy"
        next_action = "Continue production workflow"
    elif severity == "warn":
        label = "Needs Attention"
        next_action = "Run reconciliation apply or maintenance when safe"
    else:
        label = "Failed"
        next_action = "Open diagnostics and repair project state"
    return {
        "version": 1,
        "updated_at": report["updated_at"],
        "local_only": True,
        "integrity_status": label,
        "severity": severity,
        "issue_count": report["issue_count"],
        "repairable_issue_count": report["repairable_issue_count"],
        "summary": report.get("summary", {}),
        "next_action": next_action,
        "warnings": [issue["message"] for issue in report.get("issues", [])[:5] if issue.get("severity") != "pass"],
    }


def _quarantine_report(config: AppConfig, issues: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    quarantine_dir = config.root / "out" / "quarantine"
    metadata_issues = [issue for issue in issues if issue.get("repairable") and issue.get("kind") in {"missing_db_clip_row", "task_snapshot_mismatch", "stale_school_report_clip", "client_tasks_missing", "runtime_snapshot_missing"}]
    manifest = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "applied": apply,
        "quarantine_dir": str(quarantine_dir),
        "metadata_only": True,
        "items": metadata_issues,
        "moved_source_media": 0,
    }
    if apply and metadata_issues:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        path = quarantine_dir / f"metadata_quarantine_{manifest['updated_at'].replace(':', '').replace('+00:00', 'Z')}.json"
        save_json_file(path, manifest)
        append_event(config, "quarantine.created", severity="warn", source="state_reconciler", summary={"items": len(metadata_issues), "path": str(path)})
        manifest["manifest_path"] = str(path)
    save_json_file(config.analytics_dir / QUARANTINE_REPORT, manifest)
    return manifest


def _apply_safe_repairs(config: AppConfig, *, limit: int | None) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    commands = [
        ["python3", "scripts/backfill_runtime_db.py", "--quick"],
        ["python3", "scripts/build_task_snapshot.py"],
        ["python3", "scripts/build_runtime_snapshot.py"],
        ["python3", "scripts/build_observability_report.py"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=config.root, capture_output=True, text=True, timeout=120)
        steps.append({"command": command, "returncode": result.returncode, "status": "pass" if result.returncode == 0 else "warn"})
    return {"steps": steps, "limit": limit}


def reconcile_state(config: AppConfig, *, apply: bool = False, limit: int | None = None) -> dict[str, Any]:
    ensure_directories(config)
    append_event(config, "reconciliation.started", severity="info", source="state_reconciler", summary={"apply": apply})
    contract = load_json_file(config.root / "config" / "state_contract.json", {})
    sections: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    for name, checker in (
        ("runtime_db", lambda: _check_runtime_db(config)),
        ("queue", lambda: _check_queue(config)),
        ("media_cache", lambda: _check_media_cache(config)),
        ("social_exports", lambda: _check_social_exports(config)),
        ("schools", lambda: _check_schools(config)),
        ("tasks", lambda: _check_tasks(config)),
        ("client_state", lambda: _check_client_state(config)),
    ):
        found, summary = checker()
        sections[name] = summary
        issues.extend(found)
    issues.extend(_check_json_files(config, contract))
    if limit:
        issues = issues[:limit]
    repairable = [issue for issue in issues if issue.get("repairable")]
    severity = "fail" if any(issue.get("severity") == "fail" for issue in issues) else ("warn" if issues else "pass")
    apply_result = _apply_safe_repairs(config, limit=limit) if apply else None
    quarantine = _quarantine_report(config, issues, apply=apply)
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": "pass" if severity != "fail" else "fail",
        "severity": severity,
        "applied": apply,
        "issue_count": len(issues),
        "repairable_issue_count": len(repairable),
        "sections": sections,
        "summary": {
            "runtime_db": sections.get("runtime_db", {}),
            "queue_entries": sections.get("queue", {}).get("queue_entries", 0),
            "missing_clip_refs": len([issue for issue in issues if issue["kind"].startswith("missing_clip")]),
            "missing_cache_files": sections.get("media_cache", {}).get("missing_cache_files", 0),
            "missing_social_export_files": sections.get("social_exports", {}).get("missing_social_export_files", 0),
        },
        "issues": issues,
        "apply_result": apply_result,
        "quarantine": quarantine,
    }
    client = _build_client_integrity(report)
    client["storage_status"] = load_json_file(config.analytics_dir / "client_storage.json", {}).get("label", "Unknown")
    save_json_file(config.analytics_dir / REPORT, report)
    save_json_file(config.analytics_dir / CLIENT_INTEGRITY, client)
    event_type = "reconciliation.repaired" if apply else ("reconciliation.needs_attention" if issues else "reconciliation.completed")
    append_event(config, event_type, severity="warn" if issues else "info", source="state_reconciler", summary={"issues": len(issues), "apply": apply})
    if apply:
        write_audit_event(config, "maintenance.run", severity="warn" if issues else "info", source="state_reconciler", summary={"action": "reconcile_apply", "issues": len(issues)})
    return {"report": report, "client_integrity": client}
