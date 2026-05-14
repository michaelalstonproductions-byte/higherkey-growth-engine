from __future__ import annotations

import fnmatch
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig, ensure_directories, load_config
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file


BACKUP_ROOT = Path("out/project_backups")
ARCHIVE_ROOT = Path("out/project_archive")
BACKUP_REPORT = "project_backup_report.json"
RESTORE_REPORT = "project_restore_report.json"
RESET_REPORT = "demo_reset_report.json"
ARCHIVE_REPORT = "project_archive_report.json"
VALIDATION_REPORT = "project_validation_report.json"
SIZE_REPORT = "project_size_report.json"

BACKUP_PATHS = (
    "config/project_manifest.json",
    "analytics/runtime_state.db",
    "analytics/events.jsonl",
    "analytics/client_state.json",
    "analytics/client_tasks.json",
    "analytics/runtime_snapshot.json",
    "queue",
    "captions",
    "clips",
    "out/social_exports",
    "out/approved_posts",
    "out/media_cache",
    "content_inbox",
    "analytics",
    "config",
)
EXCLUDE_ALWAYS = (".git/*", "node_modules/*", "dist/*", "__pycache__/*", "*.pyc")
SOURCE_MEDIA_PATTERNS = ("content_inbox/*",)
CACHE_PATTERNS = ("out/media_cache/*",)
TEST_TOKENS = ("smoke", "smoke_sample", "testsrc", "colorbar", "color_bar", "test")


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _matches(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern) for pattern in patterns)


def _iter_paths(config: AppConfig, *, include_source_media: bool = False, include_cache: bool = False) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for item in BACKUP_PATHS:
        path = config.root / item
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else [child for child in path.rglob("*") if child.is_file()]
        for candidate in candidates:
            rel = _rel(candidate, config.root)
            if _matches(rel, EXCLUDE_ALWAYS):
                continue
            if not include_source_media and _matches(rel, SOURCE_MEDIA_PATTERNS):
                continue
            if not include_cache and _matches(rel, CACHE_PATTERNS):
                continue
            if candidate.resolve() not in seen:
                seen.add(candidate.resolve())
                paths.append(candidate)
    return sorted(paths)


def backup_project(
    config: AppConfig,
    *,
    include_source_media: bool = False,
    include_cache: bool = False,
    dry_run: bool = False,
    as_folder: bool = False,
) -> dict[str, Any]:
    ensure_directories(config)
    append_event(config, "project.backup_started", source="project_lifecycle", summary={"dry_run": dry_run})
    files = _iter_paths(config, include_source_media=include_source_media, include_cache=include_cache)
    stamp = utc_now().replace(":", "").replace("+00:00", "Z")
    backup_root = config.root / BACKUP_ROOT
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_name = f"higherkey_project_backup_{stamp}"
    backup_path = backup_root / (backup_name if as_folder else f"{backup_name}.zip")
    manifest = {
        "version": 1,
        "created_at": utc_now(),
        "project_root": str(config.root),
        "include_source_media": include_source_media,
        "include_cache": include_cache,
        "file_count": len(files),
        "local_only": True,
    }
    if not dry_run:
        if as_folder:
            backup_path.mkdir(parents=True, exist_ok=False)
            for source in files:
                target = backup_path / _rel(source, config.root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            save_json_file(backup_path / "backup_manifest.json", manifest)
        else:
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                for source in files:
                    archive.write(source, _rel(source, config.root))
    report = {
        "version": 1,
        "status": "pass",
        "dry_run": dry_run,
        "backup_path": str(backup_path),
        "backup_type": "folder" if as_folder else "zip",
        "file_count": len(files),
        "included_source_media": include_source_media,
        "included_cache": include_cache,
        "local_only": True,
        "updated_at": utc_now(),
    }
    save_json_file(config.analytics_dir / BACKUP_REPORT, report)
    append_event(config, "project.backup_completed", source="project_lifecycle", summary=report)
    write_audit_event(config, "project.backed_up", source="project_lifecycle", summary={"status": report["status"], "dry_run": dry_run, "backup_path": str(backup_path)})
    return report


def restore_project(config: AppConfig, backup_path: Path, target_root: Path | None = None, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    target = (target_root or config.root).resolve()
    append_event(config, "project.restore_started", source="project_lifecycle", summary={"backup_path": str(backup_path), "target": str(target), "dry_run": dry_run})
    if not backup_path.exists():
        report = _report(config, RESTORE_REPORT, "fail", dry_run, "Backup path does not exist.", backup_path=str(backup_path), target=str(target))
        append_event(config, "project.restore_failed", severity="fail", source="project_lifecycle", summary=report)
        return report
    if target.exists() and any(target.iterdir()) and not force and not dry_run:
        report = _report(config, RESTORE_REPORT, "fail", dry_run, "Target exists. Use --force to overwrite.", backup_path=str(backup_path), target=str(target))
        append_event(config, "project.restore_failed", severity="fail", source="project_lifecycle", summary=report)
        return report
    manifest = _read_backup_manifest(backup_path)
    if not manifest:
        report = _report(config, RESTORE_REPORT, "fail", dry_run, "Backup manifest missing or invalid.", backup_path=str(backup_path), target=str(target))
        append_event(config, "project.restore_failed", severity="fail", source="project_lifecycle", summary=report)
        return report
    files = _backup_members(backup_path)
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        if backup_path.is_dir():
            for source in backup_path.rglob("*"):
                if source.is_file() and source.name != "backup_manifest.json":
                    destination = target / source.relative_to(backup_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        else:
            with zipfile.ZipFile(backup_path) as archive:
                archive.extractall(target)
        restored_config = load_config(target)
        _refresh_manifest(restored_config)
        _run_optional_snapshot(restored_config)
    report = _report(config, RESTORE_REPORT, "pass", dry_run, "Restore validated." if dry_run else "Restore completed.", backup_path=str(backup_path), target=str(target), file_count=len(files))
    append_event(config, "project.restore_completed", source="project_lifecycle", summary=report)
    write_audit_event(config, "project.restored", source="project_lifecycle", summary={"status": report["status"], "dry_run": dry_run, "target": str(target)})
    return report


def reset_demo_workspace(config: AppConfig, *, mode: str = "soft", archive_first: bool = False, confirm_delete_source_media: bool = False, dry_run: bool = False) -> dict[str, Any]:
    if mode not in {"soft", "hard"}:
        raise ValueError("mode must be soft or hard")
    append_event(config, "project.reset_started", source="project_lifecycle", summary={"mode": mode, "dry_run": dry_run})
    backup = backup_project(config, dry_run=dry_run) if archive_first else None
    targets = [
        config.queue_dir,
        config.clips_dir,
        config.captions_dir,
        config.root / "out" / "social_exports",
        config.root / "out" / "approved_posts",
        config.root / "out" / "media_cache",
    ]
    files = [
        config.analytics_dir / "runtime_snapshot.json",
        config.analytics_dir / "client_state.json",
        config.analytics_dir / "client_tasks.json",
        config.analytics_dir / "media_cache.json",
    ]
    if mode == "hard":
        if not confirm_delete_source_media:
            report = _report(config, RESET_REPORT, "fail", dry_run, "Hard reset requires --confirm-delete-source-media.", mode=mode)
            append_event(config, "project.reset_completed", severity="fail", source="project_lifecycle", summary=report)
            return report
        targets.append(config.inbox_dir)
    changed = [str(path) for path in targets + files]
    if not dry_run:
        for path in targets:
            if path.exists():
                shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
        for path in files:
            if path.exists():
                path.unlink()
        _run_optional_snapshot(config)
    report = _report(config, RESET_REPORT, "pass", dry_run, "Reset validated." if dry_run else "Reset completed.", mode=mode, archive_first=archive_first, backup=backup, changed_paths=changed)
    append_event(config, "project.reset_completed", source="project_lifecycle", summary=report)
    write_audit_event(config, "project.reset_demo", source="project_lifecycle", summary={"status": report["status"], "dry_run": dry_run, "mode": mode})
    return report


def archive_project_artifacts(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    append_event(config, "project.archive_started", source="project_lifecycle", summary={"dry_run": dry_run})
    archive_root = config.root / ARCHIVE_ROOT / utc_now().replace(":", "").replace("+00:00", "Z")
    candidates = []
    for base in (config.inbox_dir, config.clips_dir, config.root / "out" / "media_cache"):
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file() and _looks_test(path):
                    candidates.append(path)
    for path in (config.analytics_dir / "qa_report.json", config.analytics_dir / "project_repair_report.json"):
        if path.exists():
            candidates.append(path)
    if not dry_run:
        for source in candidates:
            target = archive_root / _rel(source, config.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
    report = _report(config, ARCHIVE_REPORT, "pass", dry_run, "Archive validated." if dry_run else "Archive completed.", archive_path=str(archive_root), archived_count=len(candidates), archived_paths=[_rel(path, config.root) for path in candidates])
    append_event(config, "project.archive_completed", source="project_lifecycle", summary=report)
    write_audit_event(config, "media.archived", source="project_lifecycle", summary={"status": report["status"], "dry_run": dry_run, "archived_count": len(candidates)})
    return report


def validate_project(config: AppConfig) -> dict[str, Any]:
    required_folders = ["content_inbox", "analytics", "queue", "clips", "captions", "logs", "out", "config"]
    checks = []
    for folder in required_folders:
        path = config.root / folder
        checks.append({"name": f"folder:{folder}", "status": "pass" if path.exists() and path.is_dir() else "fail", "path": str(path)})
    required_files = [
        config.root / "config" / "project_manifest.json",
        config.analytics_dir / "runtime_state.db",
        config.analytics_dir / "events.jsonl",
        config.queue_path,
        config.analytics_dir / "client_state.json",
        config.analytics_dir / "client_tasks.json",
        config.analytics_dir / "local_api_status.json",
        config.analytics_dir / "worker_runtime_status.json",
    ]
    for path in required_files:
        checks.append({"name": f"file:{_safe_rel(path, config.root)}", "status": "pass" if path.exists() else "warn", "path": str(path)})
    queue = load_json_file(config.queue_path, {"entries": []})
    entries = queue.get("entries", []) if isinstance(queue, dict) else []
    missing_clips = []
    for entry in entries[:500]:
        clip_path = entry.get("clip_path")
        if clip_path and not (config.root / clip_path).exists():
            missing_clips.append(clip_path)
    if missing_clips:
        checks.append({"name": "media_references", "status": "warn", "missing_clip_refs": len(missing_clips)})
    status = "fail" if any(check["status"] == "fail" for check in checks) else ("warn" if any(check["status"] == "warn" for check in checks) else "pass")
    report = {
        "version": 1,
        "status": status,
        "updated_at": utc_now(),
        "local_only": True,
        "checks": checks,
        "summary": {"checks": len(checks), "queue_entries": len(entries), "missing_clip_refs": len(missing_clips)},
    }
    save_json_file(config.analytics_dir / VALIDATION_REPORT, report)
    append_event(config, "project.validation_completed", severity="info" if status != "fail" else "fail", source="project_lifecycle", summary=report["summary"])
    write_audit_event(config, "diagnostics.run", severity="info" if status != "fail" else "fail", source="project_lifecycle", summary={"report": VALIDATION_REPORT, "status": status})
    return report


def project_size_report(config: AppConfig) -> dict[str, Any]:
    buckets = {
        "content_inbox": config.inbox_dir,
        "clips": config.clips_dir,
        "captions": config.captions_dir,
        "media_cache": config.root / "out" / "media_cache",
        "social_exports": config.root / "out" / "social_exports",
        "approved_posts": config.root / "out" / "approved_posts",
        "analytics": config.analytics_dir,
        "backups": config.root / BACKUP_ROOT,
    }
    sizes = {name: _dir_size(path) for name, path in buckets.items()}
    largest = sorted(_all_files(config.root), key=lambda item: item["size_bytes"], reverse=True)[:20]
    cleanup = []
    if sizes.get("media_cache", 0) > 2_000_000_000:
        cleanup.append("Media cache is large; archive or rebuild cache.")
    if sizes.get("backups", 0) > 5_000_000_000:
        cleanup.append("Project backups are large; move older backups to external storage.")
    if not cleanup:
        cleanup.append("No cleanup needed.")
    report = {
        "version": 1,
        "status": "pass",
        "updated_at": utc_now(),
        "local_only": True,
        "sizes": sizes,
        "total_size_bytes": sum(sizes.values()),
        "largest_files": largest,
        "cleanup_suggestions": cleanup,
    }
    save_json_file(config.analytics_dir / SIZE_REPORT, report)
    append_event(config, "project.size_report_completed", source="project_lifecycle", summary={"total_size_bytes": report["total_size_bytes"]})
    write_audit_event(config, "maintenance.run", source="project_lifecycle", summary={"report": SIZE_REPORT, "total_size_bytes": report["total_size_bytes"]})
    return report


def lifecycle_summary(config: AppConfig) -> dict[str, Any]:
    return {
        "validation": load_json_file(config.analytics_dir / VALIDATION_REPORT, {}),
        "size_report": load_json_file(config.analytics_dir / SIZE_REPORT, {}),
        "backup": load_json_file(config.analytics_dir / BACKUP_REPORT, {}),
        "restore": load_json_file(config.analytics_dir / RESTORE_REPORT, {}),
        "reset": load_json_file(config.analytics_dir / RESET_REPORT, {}),
        "archive": load_json_file(config.analytics_dir / ARCHIVE_REPORT, {}),
        "backups": list_backups(config),
    }


def list_backups(config: AppConfig) -> list[dict[str, Any]]:
    root = config.root / BACKUP_ROOT
    if not root.exists():
        return []
    items = []
    for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix != ".zip":
            continue
        items.append({"path": str(path), "name": path.name, "size_bytes": _path_size(path), "updated_at": path.stat().st_mtime})
    return items[:50]


def _report(config: AppConfig, filename: str, status: str, dry_run: bool, message: str, **extra: Any) -> dict[str, Any]:
    report = {"version": 1, "status": status, "dry_run": dry_run, "message": message, "updated_at": utc_now(), "local_only": True, **extra}
    save_json_file(config.analytics_dir / filename, report)
    return report


def _read_backup_manifest(path: Path) -> dict[str, Any]:
    if path.is_dir():
        return load_json_file(path / "backup_manifest.json", {})
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read("backup_manifest.json").decode("utf-8"))
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return {}


def _backup_members(path: Path) -> list[str]:
    if path.is_dir():
        return [item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()]
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return []


def _refresh_manifest(config: AppConfig) -> None:
    manifest_path = config.root / "config" / "project_manifest.json"
    manifest = load_json_file(manifest_path, {})
    manifest.update({
        "project_root": str(config.root),
        "content_inbox": str(config.inbox_dir),
        "runtime_db": str(config.analytics_dir / "runtime_state.db"),
        "updated_at": utc_now(),
        "local_only": True,
    })
    save_json_file(manifest_path, manifest)


def _run_optional_snapshot(config: AppConfig) -> None:
    try:
        from scripts.build_runtime_snapshot import build_snapshot

        build_snapshot(config.root)
    except Exception:
        pass


def _looks_test(path: Path) -> bool:
    text = path.name.lower()
    return any(token in text for token in TEST_TOKENS)


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return _rel(path, root)
    except ValueError:
        return str(path)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return _dir_size(path)


def _all_files(root: Path) -> list[dict[str, Any]]:
    excluded = {"node_modules", ".git", "dist"}
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(root).parts):
            continue
        files.append({"path": _rel(path, root), "size_bytes": path.stat().st_size})
    return files
