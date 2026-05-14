from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig, ensure_directories
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .runtime_db import db_path
from .security import require_confirmation, validate_runtime_path


RETENTION_POLICY = "retention_policy.json"
ARCHIVE_ROOT = Path("out/archives")
PROTECTED_CATEGORIES = {"source_footage", "runtime_database", "approved_exports", "old_social_export_packs"}


def load_retention_policy(config: AppConfig) -> dict[str, Any]:
    policy = load_json_file(config.root / "config" / RETENTION_POLICY, {})
    if not isinstance(policy, dict) or "rules" not in policy:
        return {"version": 1, "local_only": True, "rules": {}}
    return policy


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _path_age_days(path: Path) -> float:
    if not path.exists():
        return 0.0
    newest = 0.0
    paths = [path] if path.is_file() else [item for item in path.rglob("*") if item.exists()]
    for item in paths:
        try:
            newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    if newest <= 0:
        return 0.0
    return max(0.0, (__import__("time").time() - newest) / 86400)


def _category_entries(config: AppConfig) -> list[dict[str, Any]]:
    policy = load_retention_policy(config)
    entries: list[dict[str, Any]] = []
    defaults = policy.get("defaults", {})
    for category, rule in (policy.get("rules") or {}).items():
        merged = {**defaults, **rule}
        for rel_path in merged.get("paths", []):
            path = (config.root / rel_path).resolve()
            entries.append({
                "category": category,
                "path": path,
                "relative_path": _rel(path, config.root),
                "rule": merged,
            })
    return entries


def measure_storage(config: AppConfig) -> dict[str, Any]:
    ensure_directories(config)
    categories = []
    total_generated = 0
    for entry in _category_entries(config):
        path = entry["path"]
        size_bytes = _size(path)
        count = _file_count(path)
        if not entry["rule"].get("protected", False):
            total_generated += size_bytes
        categories.append({
            "category": entry["category"],
            "path": entry["relative_path"],
            "exists": path.exists(),
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 3),
            "file_count": count,
            "age_days": round(_path_age_days(path), 2),
            "protected": bool(entry["rule"].get("protected", False)),
            "client_visible": bool(entry["rule"].get("client_visible", True)),
            "delete_allowed": bool(entry["rule"].get("delete_allowed", False)),
        })
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "local_only": True,
        "project_root": str(config.root),
        "total_generated_size_bytes": total_generated,
        "total_generated_size_mb": round(total_generated / (1024 * 1024), 3),
        "categories": categories,
    }
    save_json_file(config.analytics_dir / "cache_report.json", report)
    client = build_client_storage(report)
    save_json_file(config.analytics_dir / "client_storage.json", client)
    append_event(config, "storage.report_completed", severity="info", source="cache_manager", summary={"total_generated_size_mb": report["total_generated_size_mb"]})
    return report


def build_client_storage(report: dict[str, Any]) -> dict[str, Any]:
    visible = [item for item in report.get("categories", []) if item.get("client_visible")]
    generated_mb = float(report.get("total_generated_size_mb") or 0)
    cleanup_candidates = sum(1 for item in report.get("categories", []) if item.get("delete_allowed") and item.get("size_bytes", 0) > 0)
    label = "Storage Healthy"
    status = "pass"
    if generated_mb > 8192:
        label = "Storage Needs Attention"
        status = "warn"
    elif cleanup_candidates:
        label = "Cleanup Recommended"
        status = "warn"
    return {
        "version": 1,
        "updated_at": report.get("updated_at") or utc_now(),
        "local_only": True,
        "status": status,
        "label": label,
        "generated_size_mb": generated_mb,
        "cleanup_candidate_count": cleanup_candidates,
        "protected_original_footage": True,
        "categories": [
            {
                "category": item["category"],
                "size_mb": item["size_mb"],
                "file_count": item["file_count"],
                "protected": item["protected"],
            }
            for item in visible
        ],
        "next_action": "Review cleanup plan" if cleanup_candidates else "No cleanup needed",
    }


def build_cleanup_plan(
    config: AppConfig,
    *,
    category: str | None = None,
    max_age_days: int | None = None,
    max_size_mb: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    report = measure_storage(config)
    candidates = []
    for entry in _category_entries(config):
        rule = entry["rule"]
        if category and entry["category"] != category:
            continue
        path = entry["path"]
        if not path.exists():
            continue
        size_bytes = _size(path)
        size_mb = size_bytes / (1024 * 1024)
        age_days = _path_age_days(path)
        rule_age = max_age_days if max_age_days is not None else int(rule.get("max_age_days", 0) or 0)
        rule_size = max_size_mb if max_size_mb is not None else int(rule.get("max_size_mb", 0) or 0)
        protected = bool(rule.get("protected", False)) or entry["category"] in PROTECTED_CATEGORIES
        over_age = bool(rule_age and age_days >= rule_age)
        over_size = bool(rule_size and size_mb >= rule_size)
        eligible = bool(rule.get("enabled", True)) and not protected and bool(rule.get("delete_allowed", False)) and bool(over_age or over_size or category)
        action = "skip"
        if eligible:
            action = "archive" if rule.get("archive_before_delete", True) else "delete"
        candidates.append({
            "category": entry["category"],
            "path": entry["relative_path"],
            "size_bytes": size_bytes,
            "size_mb": round(size_mb, 3),
            "age_days": round(age_days, 2),
            "over_age": over_age,
            "over_size": over_size,
            "protected": protected,
            "delete_allowed": bool(rule.get("delete_allowed", False)),
            "archive_before_delete": bool(rule.get("archive_before_delete", True)),
            "action": action,
            "eligible": eligible,
        })
    plan = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "dry_run": dry_run,
        "local_only": True,
        "summary": {
            "candidate_count": len(candidates),
            "eligible_count": sum(1 for item in candidates if item["eligible"]),
            "archive_count": sum(1 for item in candidates if item["action"] == "archive"),
            "delete_count": sum(1 for item in candidates if item["action"] == "delete"),
            "protected_count": sum(1 for item in candidates if item["protected"]),
            "planned_size_mb": round(sum(item["size_bytes"] for item in candidates if item["eligible"]) / (1024 * 1024), 3),
        },
        "candidates": candidates,
        "storage_report_path": "analytics/cache_report.json",
    }
    save_json_file(config.analytics_dir / "cleanup_plan.json", plan)
    save_json_file(config.analytics_dir / "client_storage.json", build_client_storage(report))
    return plan


def _archive_target(config: AppConfig, category: str, source: Path, stamp: str) -> Path:
    return config.root / ARCHIVE_ROOT / f"{category}_{stamp}" / _rel(source, config.root)


def _write_archive_history(config: AppConfig, manifest: dict[str, Any]) -> None:
    history_path = config.analytics_dir / "archive_history.json"
    history = load_json_file(history_path, {"version": 1, "archives": []})
    history.setdefault("archives", []).append(manifest)
    history["archives"] = history["archives"][-200:]
    history["updated_at"] = utc_now()
    save_json_file(history_path, history)
    save_json_file(config.analytics_dir / "archive_manifest.json", manifest)


def apply_cleanup_plan(config: AppConfig, *, confirm: bool = False, category: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    plan = build_cleanup_plan(config, category=category, dry_run=dry_run)
    if not dry_run:
        confirmation = require_confirmation(
            config,
            "delete_cache",
            confirmed=confirm,
            summary="Storage cleanup apply requested.",
            affected_paths=[item["path"] for item in plan["candidates"] if item["eligible"]],
            reversible=True,
        )
        if not confirmation["ok"]:
            result = {"version": 1, "updated_at": utc_now(), "status": "fail", "message": confirmation["message"], "plan": plan, "local_only": True}
            save_json_file(config.analytics_dir / "cleanup_history.json", result)
            return result
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    changed = []
    for item in plan["candidates"]:
        if not item["eligible"]:
            continue
        source = (config.root / item["path"]).resolve()
        security = validate_runtime_path(config, source)
        if not security["ok"] or not source.exists() or dry_run:
            continue
        if item["action"] == "archive":
            target = _archive_target(config, item["category"], source, stamp)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            changed.append({"action": "archive", "source": item["path"], "target": _rel(target, config.root)})
        elif item["action"] == "delete":
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
            changed.append({"action": "delete", "source": item["path"]})
    manifest = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "dry_run": dry_run,
        "archive_root": _rel(config.root / ARCHIVE_ROOT, config.root),
        "changed": changed,
        "local_only": True,
    }
    _write_archive_history(config, manifest)
    history = load_json_file(config.analytics_dir / "cleanup_history.json", {"version": 1, "runs": []})
    history.setdefault("runs", []).append({"updated_at": utc_now(), "dry_run": dry_run, "changed": changed, "plan_summary": plan["summary"]})
    history["runs"] = history["runs"][-200:]
    save_json_file(config.analytics_dir / "cleanup_history.json", history)
    append_event(config, "storage.cleanup_completed", severity="info", source="cache_manager", summary={"dry_run": dry_run, "changed": len(changed)})
    write_audit_event(config, "maintenance.run", source="cache_manager", summary={"storage_cleanup": True, "dry_run": dry_run, "changed": len(changed)})
    return {"version": 1, "updated_at": utc_now(), "status": "pass", "dry_run": dry_run, "plan": plan, "archive_manifest": manifest, "changed": changed, "local_only": True}


def archive_generated_artifacts(config: AppConfig, *, confirm: bool = False, dry_run: bool = True, category: str | None = None) -> dict[str, Any]:
    return apply_cleanup_plan(config, confirm=confirm, category=category, dry_run=dry_run)


def vacuum_runtime_db(config: AppConfig, *, dry_run: bool = True) -> dict[str, Any]:
    path = db_path(config)
    before = path.stat().st_size if path.exists() else 0
    if not dry_run and path.exists():
        with sqlite3.connect(path) as connection:
            connection.execute("VACUUM")
    after = path.stat().st_size if path.exists() else 0
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "dry_run": dry_run,
        "runtime_db": str(path),
        "before_bytes": before,
        "after_bytes": after,
        "local_only": True,
    }
    append_event(config, "storage.vacuum_checked", severity="info", source="cache_manager", summary={"dry_run": dry_run})
    return report
