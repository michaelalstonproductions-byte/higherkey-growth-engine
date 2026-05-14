from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analytics import save_json
from .config import AppConfig, ensure_directories, load_config
from .events import append_event
from .index import utc_now
from .audit import audit_summary, read_recent_audit_events, write_audit_event
from .observability import build_observability_report, write_metrics
from .task_queue import list_tasks, task_summary
from .worker_runtime import health as worker_health
from .project_lifecycle import lifecycle_summary, list_backups
from .state_reconciler import reconcile_state
from .cache_manager import archive_generated_artifacts, apply_cleanup_plan, build_cleanup_plan, measure_storage, vacuum_runtime_db
from .migrations import apply_upgrade, build_upgrade_plan
from .security import (
    generate_local_api_token,
    require_confirmation,
    security_summary,
    validate_api_request,
    validate_project_root,
    validate_runtime_path,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
STATUS_FILE = "local_api_status.json"
HISTORY_FILE = "local_api_history.json"


def response_envelope(
    *,
    ok: bool = True,
    status: str = "pass",
    data: dict[str, Any] | list[Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": status,
        "data": data if data is not None else {},
        "message": message,
        "updated_at": utc_now(),
        "local_only": True,
    }


def status_path(config: AppConfig) -> Path:
    return config.analytics_dir / STATUS_FILE


def history_path(config: AppConfig) -> Path:
    return config.analytics_dir / HISTORY_FILE


def write_status(config: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_directories(config)
    status = {
        "version": 1,
        "local_only": True,
        "updated_at": utc_now(),
        **payload,
    }
    save_json(status_path(config), status)
    history = []
    if history_path(config).exists():
        try:
            loaded = json.loads(history_path(config).read_text(encoding="utf-8"))
            history = loaded if isinstance(loaded, list) else []
        except json.JSONDecodeError:
            history = []
    history.append(status)
    save_json(history_path(config), history[-100:])
    return status


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def recent_events(config: AppConfig, limit: int = 50) -> list[dict[str, Any]]:
    path = config.analytics_dir / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 200)) :]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def media_summary(config: AppConfig) -> dict[str, Any]:
    queue = load_json(config.queue_path, {})
    entries = queue.get("entries", []) if isinstance(queue, dict) else []
    cache = load_json(config.analytics_dir / "media_cache.json", {})
    repair = load_json(config.analytics_dir / "project_repair_report.json", {})
    production = [entry for entry in entries if not _is_test_entry(entry)]
    approved = [entry for entry in production if str(entry.get("decision") or entry.get("status") or "").lower() == "approved"]
    return {
        "total_clips": len(entries),
        "production_clips": len(production),
        "approved_clips": len(approved),
        "hidden_test_media_count": len(entries) - len(production),
        "media_cache_count": len(cache.get("assets", [])) if isinstance(cache, dict) else 0,
        "missing_sources": repair.get("counts", {}).get("missing_sources", 0) if isinstance(repair, dict) else 0,
        "queue_path": str(config.queue_path),
    }


def pipeline_status(config: AppConfig) -> dict[str, Any]:
    return load_json(config.analytics_dir / "pipeline_status.json", {"status": "unknown", "message": "Pipeline status unavailable."})


def social_exports(config: AppConfig) -> dict[str, Any]:
    return {
        "history": load_json(config.analytics_dir / "social_export_history.json", {}),
        "manifest": load_json(config.root / "out" / "social_exports" / "manifest.json", {}),
    }


def _is_test_entry(entry: dict[str, Any]) -> bool:
    text = " ".join(str(entry.get(key, "")) for key in ("clip_id", "clip_path", "source_path", "filename", "name")).lower()
    return any(token in text for token in ("smoke_sample", "smoke", "testsrc", "colorbar", "color_bar", "test"))


def run_script(config: AppConfig, args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    command = ["python3", str(config.root / args[0]), *args[1:]]
    try:
        result = subprocess.run(command, cwd=config.root, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "status": "fail", "message": "Local command timed out."}
    parsed = None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = None
    payload = {
        "returncode": result.returncode,
        "status": "pass" if result.returncode == 0 else "fail",
        "parsed": parsed,
    }
    if result.returncode != 0:
        payload["message"] = "Local command failed. Technical details are available in diagnostics."
    return payload


class LocalApiHandler(BaseHTTPRequestHandler):
    server_version = "HigherKeyLocalAPI/1.0"

    def do_OPTIONS(self) -> None:
        if not self._is_local_request():
            self._send_json(response_envelope(ok=False, status="fail", message="Only localhost requests are allowed."), code=403)
            return
        self.send_response(204)
        self._write_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if not self._is_local_request():
            self._send_json(response_envelope(ok=False, status="fail", message="Only localhost requests are allowed."), code=403)
            return
        parsed = urlparse(self.path)
        try:
            data, message = self._handle_get(parsed.path, parse_qs(parsed.query))
            self._send_json(response_envelope(data=data, message=message))
        except KeyError:
            self._send_json(response_envelope(ok=False, status="fail", message="Unknown local API endpoint."), code=404)
        except Exception:
            append_event(self.config, "api.failed", severity="fail", source="local_api", summary={"path": parsed.path})
            self._send_json(response_envelope(ok=False, status="fail", message="Local API request failed. See diagnostics."), code=500)

    def do_POST(self) -> None:
        if not self._is_local_request():
            self._send_json(response_envelope(ok=False, status="fail", message="Only localhost requests are allowed."), code=403)
            return
        parsed = urlparse(self.path)
        try:
            body = self._read_body()
            action = self._action_for_post(parsed.path)
            token = self.headers.get("X-HigherKey-Token") or str(body.get("token") or "")
            security = validate_api_request(
                self.config,
                host=self.client_address[0],
                header_host=self.headers.get("Host") or "",
                method="POST",
                token=token or None,
                action=action,
            )
            if not security["ok"]:
                self._send_json(response_envelope(ok=False, status="fail", data=security, message=security["message"]), code=403)
                return
            write_audit_event(self.config, "settings.changed", severity="info", source="local_api", summary={"post_action": action, "path": parsed.path})
            data, message, status = self._handle_post(parsed.path, body)
            self._send_json(response_envelope(status=status, data=data, message=message))
        except KeyError:
            self._send_json(response_envelope(ok=False, status="fail", message="Unknown local API endpoint."), code=404)
        except Exception:
            append_event(self.config, "api.failed", severity="fail", source="local_api", summary={"path": parsed.path})
            self._send_json(response_envelope(ok=False, status="fail", message="Local API action failed. See diagnostics."), code=500)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def config(self) -> AppConfig:
        return self.server.config  # type: ignore[attr-defined]

    def _is_local_request(self) -> bool:
        host = self.client_address[0]
        header_host = (self.headers.get("Host") or "").split(":")[0]
        return host in {"127.0.0.1", "::1"} and (not header_host or header_host in LOCAL_HOSTS)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 1024 * 256)).decode("utf-8")
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[dict[str, Any] | list[Any], str]:
        config = self.config
        if path == "/health":
            append_event(config, "api.health_checked", severity="info", source="local_api", summary={"endpoint": path})
            return {"status": "pass", "service": "local_api", "host": self.server.server_address[0], "port": self.server.server_address[1]}, "Local API healthy."
        if path == "/state/client":
            return load_json(config.analytics_dir / "client_state.json", {}), "Client state loaded."
        if path == "/state/runtime":
            return load_json(config.analytics_dir / "runtime_snapshot.json", {}), "Runtime state loaded."
        if path == "/tasks":
            limit = int((query.get("limit") or ["100"])[0])
            return {"tasks": list_tasks(config, limit=max(1, min(limit, 500)))}, "Tasks loaded."
        if path == "/tasks/summary":
            snapshot = load_json(config.analytics_dir / "client_tasks.json", {})
            return {"summary": task_summary(config), "client_tasks": snapshot}, "Task summary loaded."
        if path == "/worker/status":
            return worker_health(config), "Worker status loaded."
        if path == "/events/recent":
            limit = int((query.get("limit") or ["50"])[0])
            return {"events": recent_events(config, limit=limit)}, "Recent events loaded."
        if path == "/project/manifest":
            return load_json(config.root / "config" / "project_manifest.json", {}), "Project manifest loaded."
        if path == "/project/validation":
            return load_json(config.analytics_dir / "project_validation_report.json", {}), "Project validation loaded."
        if path == "/project/size":
            return load_json(config.analytics_dir / "project_size_report.json", {}), "Project size report loaded."
        if path == "/project/backups":
            return {"backups": list_backups(config)}, "Project backups loaded."
        if path == "/project/lifecycle":
            return lifecycle_summary(config), "Project lifecycle summary loaded."
        if path == "/media/summary":
            return media_summary(config), "Media summary loaded."
        if path == "/pipeline/status":
            return pipeline_status(config), "Pipeline status loaded."
        if path == "/diagnostics":
            return {"diagnostics": load_json(config.analytics_dir / "diagnostics.json", {}), "qa": load_json(config.analytics_dir / "qa_report.json", {})}, "Diagnostics loaded."
        if path == "/social/exports":
            return social_exports(config), "Social exports loaded."
        if path == "/schools/color":
            return load_json(config.analytics_dir / "color_school_report.json", {}), "Color School report loaded."
        if path == "/schools/audio":
            return load_json(config.analytics_dir / "audio_school_report.json", {}), "Audio School report loaded."
        if path == "/metrics/runtime":
            return load_json(config.analytics_dir / "runtime_metrics.json", write_metrics(config)["runtime_metrics"]), "Runtime metrics loaded."
        if path == "/metrics/client":
            return load_json(config.analytics_dir / "client_metrics.json", write_metrics(config)["client_metrics"]), "Client metrics loaded."
        if path == "/audit/recent":
            limit = int((query.get("limit") or ["50"])[0])
            return {"events": read_recent_audit_events(config, limit=limit), "summary": audit_summary(config)}, "Recent audit events loaded."
        if path == "/observability/report":
            return load_json(config.analytics_dir / "observability_report.json", build_observability_report(config)["observability_report"]), "Observability report loaded."
        if path == "/health/score":
            metrics = load_json(config.analytics_dir / "client_metrics.json", write_metrics(config)["client_metrics"])
            return {"health_score": metrics.get("health_score"), "health_label": metrics.get("health_label"), "runtime_status": metrics.get("runtime_status")}, "Health score loaded."
        if path == "/state/integrity":
            return load_json(config.analytics_dir / "client_integrity.json", {}), "Client integrity loaded."
        if path == "/state/reconciliation":
            return load_json(config.analytics_dir / "state_reconciliation_report.json", {}), "State reconciliation report loaded."
        if path == "/security/status":
            return security_summary(config), "Security status loaded."
        if path == "/storage/report":
            return load_json(config.analytics_dir / "cache_report.json", measure_storage(config)), "Storage report loaded."
        if path == "/storage/client":
            return load_json(config.analytics_dir / "client_storage.json", {}), "Client storage loaded."
        if path == "/cleanup/plan":
            return load_json(config.analytics_dir / "cleanup_plan.json", build_cleanup_plan(config)), "Cleanup plan loaded."
        if path == "/upgrade/status":
            return load_json(config.analytics_dir / "client_upgrade_status.json", {}), "Upgrade status loaded."
        if path == "/upgrade/plan":
            return load_json(config.analytics_dir / "upgrade_plan.json", build_upgrade_plan(config)), "Upgrade plan loaded."
        if path == "/launch/preflight":
            return load_json(config.analytics_dir / "launch_preflight.json", {}), "Launch preflight loaded."
        if path == "/contracts/data":
            return load_json(config.analytics_dir / "data_contract_report.json", {}), "Data contract report loaded."
        raise KeyError(path)

    def _handle_post(self, path: str, body: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        config = self.config
        if path == "/tasks/enqueue/full-media-prep":
            args = ["scripts/enqueue_full_media_prep.py"] + (["--dry-run"] if body.get("dry_run") else [])
            result = run_script(config, args, timeout=60)
            append_event(config, "api.task_enqueued", severity="info" if result["returncode"] == 0 else "fail", source="local_api", summary={"task": "full_media_prep"})
            message = "Full Media Prep task chain validated." if body.get("dry_run") else "Full Media Prep task chain enqueued."
            return result, message if result["returncode"] == 0 else "Unable to enqueue Full Media Prep.", result["status"]
        if path == "/worker/once":
            return self._worker_command("once")
        if path == "/worker/start":
            return self._worker_command("start")
        if path == "/worker/stop":
            return self._worker_command("stop")
        if path == "/worker/pause":
            return self._worker_command("pause")
        if path == "/worker/resume":
            return self._worker_command("resume")
        if path == "/maintenance/run":
            dry_run = bool(body.get("dry_run", False))
            args = ["scripts/run_maintenance.py"] + (["--dry-run"] if dry_run else [])
            result = run_script(config, args, timeout=240)
            append_event(config, "api.maintenance_requested", severity="info" if result["returncode"] == 0 else "fail", source="local_api", summary={"dry_run": dry_run})
            return result, "Maintenance completed." if result["returncode"] == 0 else "Maintenance needs attention.", result["status"]
        if path == "/snapshot/build":
            result = run_script(config, ["scripts/build_runtime_snapshot.py"], timeout=90)
            append_event(config, "api.snapshot_built", severity="info" if result["returncode"] == 0 else "fail", source="local_api", summary={"status": result["status"]})
            return result, "Runtime snapshot built." if result["returncode"] == 0 else "Runtime snapshot failed.", result["status"]
        if path == "/repair/run":
            result = run_script(config, ["scripts/repair_project_media.py"], timeout=180)
            append_event(config, "repair.completed", severity="info" if result["returncode"] == 0 else "fail", source="local_api", summary={"status": result["status"]})
            return result, "Project media repair completed." if result["returncode"] == 0 else "Project media repair needs attention.", result["status"]
        if path == "/project/backup":
            confirmation = require_confirmation(
                config,
                "backup_project",
                confirmed=bool(body.get("confirmed") or body.get("dry_run")),
                summary="Project backup requested through local API.",
                affected_paths=["out/project_backups"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            args = ["scripts/backup_project.py"]
            if body.get("dry_run"):
                args.append("--dry-run")
            if body.get("include_source_media"):
                args.append("--include-source-media")
            if body.get("include_cache"):
                args.append("--include-cache")
            result = run_script(config, args, timeout=240)
            return result, "Project backup completed." if result["returncode"] == 0 else "Project backup needs attention.", result["status"]
        if path == "/project/restore":
            backup_path = str(body.get("backup_path") or "")
            if not backup_path:
                return {"status": "fail"}, "backup_path is required.", "fail"
            confirmation = require_confirmation(
                config,
                "restore_project",
                confirmed=bool(body.get("confirmed") or body.get("dry_run")),
                summary="Project restore requested through local API.",
                affected_paths=[backup_path, str(body.get("target") or config.root)],
                reversible=False,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            args = ["scripts/restore_project.py", backup_path]
            if body.get("dry_run"):
                args.append("--dry-run")
            if body.get("target"):
                args.extend(["--target", str(body["target"])])
            if body.get("force"):
                args.append("--force")
            result = run_script(config, args, timeout=240)
            return result, "Project restore completed." if result["returncode"] == 0 else "Project restore needs attention.", result["status"]
        if path == "/project/reset-demo":
            confirmation = require_confirmation(
                config,
                "reset_demo_workspace",
                confirmed=bool(body.get("confirmed") or body.get("dry_run")),
                summary="Demo reset requested through local API.",
                affected_paths=["queue", "clips", "captions", "out", "analytics"],
                reversible=bool(body.get("archive_first")),
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            args = ["scripts/reset_demo_workspace.py", "--hard" if body.get("hard") else "--soft"]
            if body.get("dry_run"):
                args.append("--dry-run")
            if body.get("archive_first"):
                args.append("--archive-first")
            if body.get("confirm_delete_source_media"):
                args.append("--confirm-delete-source-media")
            result = run_script(config, args, timeout=240)
            return result, "Demo reset completed." if result["returncode"] == 0 else "Demo reset needs attention.", result["status"]
        if path == "/project/archive":
            confirmation = require_confirmation(
                config,
                "archive_project_artifacts",
                confirmed=bool(body.get("confirmed") or body.get("dry_run")),
                summary="Project artifact archive requested through local API.",
                affected_paths=["out/project_archive"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            args = ["scripts/archive_project_artifacts.py"] + (["--dry-run"] if body.get("dry_run") else [])
            result = run_script(config, args, timeout=180)
            return result, "Project archive completed." if result["returncode"] == 0 else "Project archive needs attention.", result["status"]
        if path == "/project/validate":
            result = run_script(config, ["scripts/validate_project.py"], timeout=90)
            return result, "Project validation completed." if result["returncode"] == 0 else "Project validation needs attention.", result["status"]
        if path == "/project/size-report":
            result = run_script(config, ["scripts/project_size_report.py"], timeout=90)
            return result, "Project size report completed." if result["returncode"] == 0 else "Project size report needs attention.", result["status"]
        if path == "/state/reconcile":
            limit = body.get("limit")
            result = reconcile_state(config, apply=False, limit=int(limit) if limit else None)
            return result, "State reconciliation dry-run completed.", result["report"]["status"]
        if path == "/state/reconcile/apply":
            confirmation = require_confirmation(
                config,
                "reconcile_apply",
                confirmed=bool(body.get("confirmed")),
                summary="State reconciliation apply requested through local API.",
                affected_paths=["analytics", "queue"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            limit = body.get("limit")
            result = reconcile_state(config, apply=True, limit=int(limit) if limit else None)
            return result, "Safe state reconciliation repairs applied.", result["report"]["status"]
        if path == "/security/validate-path":
            target = str(body.get("path") or "")
            if not target:
                return {"status": "fail"}, "path is required.", "fail"
            kind = str(body.get("kind") or "runtime")
            result = validate_project_root(config, target) if kind == "project" else validate_runtime_path(config, target)
            return result, result["message"], result["status"]
        if path == "/security/rotate-token":
            result = generate_local_api_token(config)
            return result, "Local API token rotated.", "pass"
        if path == "/cleanup/plan":
            result = build_cleanup_plan(
                config,
                category=str(body.get("category")) if body.get("category") else None,
                max_age_days=int(body["max_age_days"]) if body.get("max_age_days") else None,
                max_size_mb=int(body["max_size_mb"]) if body.get("max_size_mb") else None,
                dry_run=True,
            )
            return result, "Cleanup plan built.", result["status"]
        if path == "/cleanup/apply":
            confirmation = require_confirmation(
                config,
                "delete_cache",
                confirmed=bool(body.get("confirmed")),
                summary="Cleanup apply requested through local API.",
                affected_paths=["analytics/cleanup_plan.json"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            result = apply_cleanup_plan(config, confirm=True, category=str(body.get("category")) if body.get("category") else None, dry_run=False)
            return result, "Cleanup applied.", result["status"]
        if path == "/cleanup/archive":
            confirmation = require_confirmation(
                config,
                "delete_cache",
                confirmed=bool(body.get("confirmed")),
                summary="Generated artifact archive requested through local API.",
                affected_paths=["out/archives"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            result = archive_generated_artifacts(config, confirm=True, category=str(body.get("category")) if body.get("category") else None, dry_run=False)
            return result, "Generated artifacts archived.", result["status"]
        if path == "/storage/vacuum-db":
            confirmation = require_confirmation(
                config,
                "delete_cache",
                confirmed=bool(body.get("confirmed")),
                summary="Runtime database vacuum requested through local API.",
                affected_paths=["analytics/runtime_state.db"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            result = vacuum_runtime_db(config, dry_run=False)
            return result, "Runtime database vacuum complete.", result["status"]
        if path == "/upgrade/check":
            result = build_upgrade_plan(config)
            return result, "Upgrade check completed.", result["status"]
        if path == "/upgrade/apply":
            confirmation = require_confirmation(
                config,
                "reconcile_apply",
                confirmed=bool(body.get("confirmed")),
                summary="Upgrade apply requested through local API.",
                affected_paths=["analytics/upgrade_report.json", "analytics/runtime_state.db"],
                reversible=True,
            )
            if not confirmation["ok"]:
                return confirmation, confirmation["message"], "fail"
            result = apply_upgrade(config, force=bool(body.get("force")))
            return result, "Upgrade apply completed.", result["status"]
        raise KeyError(path)

    def _action_for_post(self, path: str) -> str:
        mapping = {
            "/tasks/enqueue/full-media-prep": "enqueue_full_media_prep",
            "/worker/once": "worker_manage",
            "/worker/start": "worker_manage",
            "/worker/stop": "worker_manage",
            "/worker/pause": "worker_manage",
            "/worker/resume": "worker_manage",
            "/maintenance/run": "maintenance",
            "/snapshot/build": "build_runtime_snapshot",
            "/repair/run": "repair_project_media",
            "/project/backup": "backup_project",
            "/project/restore": "restore_project",
            "/project/reset-demo": "reset_demo_workspace",
            "/project/archive": "archive_project_artifacts",
            "/project/validate": "validate_project",
            "/project/size-report": "project_size_report",
            "/state/reconcile": "reconcile_dry_run",
            "/state/reconcile/apply": "reconcile_apply",
            "/security/validate-path": "security_check",
            "/security/rotate-token": "security_check",
            "/cleanup/plan": "cleanup_plan",
            "/cleanup/apply": "cleanup_apply",
            "/cleanup/archive": "archive_generated_artifacts",
            "/storage/vacuum-db": "vacuum_runtime_db",
            "/upgrade/check": "maintenance",
            "/upgrade/apply": "maintenance",
        }
        if path not in mapping:
            raise KeyError(path)
        return mapping[path]

    def _worker_command(self, command: str) -> tuple[dict[str, Any], str, str]:
        result = run_script(self.config, ["scripts/manage_worker.py", command], timeout=120)
        append_event(self.config, "api.worker_command", severity="info" if result["returncode"] == 0 else "fail", source="local_api", summary={"command": command})
        return result, f"Worker command {command} completed." if result["returncode"] == 0 else f"Worker command {command} needs attention.", result["status"]

    def _write_headers(self) -> None:
        origin = self.headers.get("Origin") or ""
        if origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, payload: dict[str, Any], *, code: int = 200) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self._write_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LocalApiServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: AppConfig) -> None:
        super().__init__(server_address, LocalApiHandler)
        self.config = config


def build_health(config: AppConfig, host: str, port: int) -> dict[str, Any]:
    return response_envelope(
        data={"service": "local_api", "host": host, "port": port, "root": str(config.root)},
        message="Local API healthy.",
    )


def run_server(config: AppConfig, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, write_status_file: bool = True) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Local API must bind to 127.0.0.1 or localhost.")
    bind_host = "127.0.0.1"
    ensure_directories(config)
    with LocalApiServer((bind_host, port), config) as server:
        actual_host, actual_port = server.server_address
        if write_status_file:
            write_status(config, {"state": "running", "host": actual_host, "port": actual_port, "pid": os.getpid()})
        append_event(config, "api.started", severity="info", source="local_api", summary={"host": actual_host, "port": actual_port})
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            if write_status_file:
                write_status(config, {"state": "stopped", "host": actual_host, "port": actual_port})


def once_health(config: AppConfig, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, write_status_file: bool = True) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Local API must bind to 127.0.0.1 or localhost.")
    payload = build_health(config, "127.0.0.1", port)
    if write_status_file:
        write_status(config, {"state": "health_checked", "host": "127.0.0.1", "port": port, "health": payload})
    append_event(config, "api.health_checked", severity="info", source="local_api", summary={"mode": "once"})
    return payload


def load_project_config(root: str | Path | None = None) -> AppConfig:
    config = load_config(Path(root).resolve() if root else Path.cwd())
    ensure_directories(config)
    return config
