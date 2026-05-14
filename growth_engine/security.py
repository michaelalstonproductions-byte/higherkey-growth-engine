from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import AppConfig, ensure_directories
from .events import append_event
from .index import utc_now
from .json_store import load_json_file, save_json_file


DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "local_only": True,
    "allowed_api_hosts": ["127.0.0.1", "localhost"],
    "allowed_project_roots": [],
    "denied_project_roots": ["/", "/Users", "/Applications", "/System", "/Library"],
    "allowed_runtime_dirs": ["analytics", "queue", "clips", "captions", "content_inbox", "logs", "out", "config"],
    "protected_dirs": ["/", "/Applications", "/System", "/Library", "/usr", "/bin", "/sbin", "/private"],
    "destructive_actions_require_confirmation": [
        "restore_project",
        "reset_demo_workspace",
        "archive_project_artifacts",
        "prune_stale_queue",
        "reconcile_apply",
        "backup_project",
        "delete_cache",
    ],
    "allow_arbitrary_file_access": False,
    "allow_arbitrary_command_execution": False,
    "max_import_file_size_mb": 20480,
    "allowed_import_extensions": [".mp4", ".mov", ".m4v"],
    "allowed_script_actions": [],
    "local_api_auth_enabled": False,
    "token_storage_path": "analytics/local_api_token.json",
    "audit_required_actions": [],
}


def load_security_policy(config: AppConfig) -> dict[str, Any]:
    path = config.root / "config" / "security_policy.json"
    policy = DEFAULT_POLICY.copy()
    loaded = load_json_file(path, {})
    if isinstance(loaded, dict):
        policy.update(loaded)
    policy["allowed_import_extensions"] = [str(item).lower() for item in policy.get("allowed_import_extensions", [])]
    return policy


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _protected_exact_paths(policy: dict[str, Any]) -> set[Path]:
    protected = {Path("/"), Path.home()}
    for value in policy.get("denied_project_roots", []) + policy.get("protected_dirs", []):
        try:
            protected.add(_resolve(value))
        except OSError:
            continue
    return protected


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_project_root(config: AppConfig, project_root: str | Path) -> dict[str, Any]:
    try:
        candidate = _resolve(project_root)
    except OSError as exc:
        return {"ok": False, "status": "fail", "message": "That folder cannot be used as a project.", "error": str(exc)}
    policy = load_security_policy(config)
    if candidate.name == "content_inbox":
        return {
            "ok": False,
            "status": "fail",
            "message": "Select the project folder, not the inbox folder.",
            "suggested_project_root": str(candidate.parent),
        }
    if candidate in _protected_exact_paths(policy):
        return {"ok": False, "status": "fail", "message": "That protected folder cannot be used as a project.", "path": str(candidate)}
    for denied in policy.get("denied_project_roots", []):
        denied_path = _resolve(denied)
        if candidate == denied_path:
            return {"ok": False, "status": "fail", "message": "That folder cannot be used as a project.", "path": str(candidate)}
    return {"ok": True, "status": "pass", "message": "Project folder is allowed.", "path": str(candidate)}


def validate_runtime_path(config: AppConfig, target_path: str | Path, *, purpose: str = "write") -> dict[str, Any]:
    try:
        target = _resolve(target_path)
    except OSError as exc:
        return {"ok": False, "status": "fail", "message": "Runtime path is invalid.", "error": str(exc)}
    root = config.root.resolve()
    if not _under(target, root):
        return {
            "ok": False,
            "status": "fail",
            "message": "Runtime writes must stay inside the active project.",
            "path": str(target),
            "project_root": str(root),
            "purpose": purpose,
        }
    return {"ok": True, "status": "pass", "message": "Runtime path is inside the active project.", "path": str(target)}


def safe_filename(filename: str) -> str:
    stem = Path(filename).stem.strip() or "media"
    suffix = Path(filename).suffix.lower()
    cleaned = re.sub(r"[^A-Za-z0-9._() -]+", "_", stem).strip(" .")
    return f"{cleaned or 'media'}{suffix}"


def validate_import_file(config: AppConfig, file_path: str | Path) -> dict[str, Any]:
    policy = load_security_policy(config)
    try:
        source = _resolve(file_path)
    except OSError as exc:
        return {"ok": False, "status": "fail", "message": "This file cannot be imported.", "error": str(exc)}
    if not source.exists() or not source.is_file():
        return {"ok": False, "status": "fail", "message": "The selected file was not found.", "path": str(source)}
    extension = source.suffix.lower()
    if extension not in policy.get("allowed_import_extensions", []):
        return {"ok": False, "status": "fail", "message": "This file type is not supported.", "path": str(source), "extension": extension}
    size_mb = source.stat().st_size / (1024 * 1024)
    max_size = float(policy.get("max_import_file_size_mb", 20480))
    if size_mb > max_size:
        return {"ok": False, "status": "fail", "message": "This file is larger than the import limit.", "path": str(source), "size_mb": round(size_mb, 2)}
    for protected in (Path("/System"), Path("/Library"), Path("/Applications")):
        if _under(source, protected):
            return {"ok": False, "status": "fail", "message": "Files from protected system folders cannot be imported.", "path": str(source)}
    return {
        "ok": True,
        "status": "pass",
        "message": "Import file is allowed.",
        "path": str(source),
        "extension": extension,
        "size_mb": round(size_mb, 3),
        "safe_filename": safe_filename(source.name),
    }


def validate_script_action(config: AppConfig, action: str) -> dict[str, Any]:
    policy = load_security_policy(config)
    allowed = set(policy.get("allowed_script_actions", []))
    if action not in allowed:
        return {"ok": False, "status": "fail", "message": "This local action is not allowed.", "action": action}
    return {"ok": True, "status": "pass", "message": "Local action is allowed.", "action": action}


def read_local_api_token(config: AppConfig) -> str | None:
    policy = load_security_policy(config)
    path = config.root / str(policy.get("token_storage_path", "analytics/local_api_token.json"))
    payload = load_json_file(path, {})
    token = payload.get("token") if isinstance(payload, dict) else None
    return str(token) if token else None


def generate_local_api_token(config: AppConfig) -> dict[str, Any]:
    policy = load_security_policy(config)
    ensure_directories(config)
    token = secrets.token_urlsafe(32)
    path = config.root / str(policy.get("token_storage_path", "analytics/local_api_token.json"))
    save_json_file(path, {"version": 1, "created_at": utc_now(), "token": token, "local_only": True})
    write_security_event(config, "security.token_rotated", severity="info", summary={"token_storage_path": str(path.relative_to(config.root))})
    return {"created_at": utc_now(), "token_suffix": token[-6:], "token_storage_path": str(path)}


def validate_api_request(
    config: AppConfig,
    *,
    host: str,
    header_host: str = "",
    method: str = "GET",
    token: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    policy = load_security_policy(config)
    allowed_hosts = set(policy.get("allowed_api_hosts", ["127.0.0.1", "localhost"]))
    header_name = header_host.split(":")[0] if header_host else ""
    if host not in {"127.0.0.1", "::1"}:
        return {"ok": False, "status": "fail", "message": "Only localhost requests are allowed."}
    if header_name and header_name not in allowed_hosts:
        return {"ok": False, "status": "fail", "message": "Only localhost requests are allowed."}
    if method.upper() == "POST" and action:
        action_check = validate_script_action(config, action)
        if not action_check["ok"]:
            return action_check
    if method.upper() == "POST" and policy.get("local_api_auth_enabled"):
        expected = read_local_api_token(config)
        if not expected or token != expected:
            return {"ok": False, "status": "fail", "message": "Local API token is required for this action."}
    return {"ok": True, "status": "pass", "message": "Local API request is allowed."}


def confirmation_receipt(
    config: AppConfig,
    action: str,
    *,
    summary: str,
    affected_paths: list[str] | None = None,
    reversible: bool = True,
) -> dict[str, Any]:
    ensure_directories(config)
    receipt = {
        "receipt_id": f"receipt_{utc_now().replace(':', '').replace('-', '')}_{secrets.token_hex(4)}",
        "action": action,
        "timestamp": utc_now(),
        "project_root": str(config.root),
        "confirmed_by": "local_operator",
        "summary": summary,
        "affected_paths": affected_paths or [],
        "reversible": reversible,
        "local_only": True,
    }
    path = config.analytics_dir / "confirmation_receipts.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
    write_audit_event(config, "settings.changed", severity="info", source="security", summary={"confirmation": action})
    return receipt


def require_confirmation(
    config: AppConfig,
    action: str,
    *,
    confirmed: bool = False,
    summary: str = "",
    affected_paths: list[str] | None = None,
    reversible: bool = True,
) -> dict[str, Any]:
    policy = load_security_policy(config)
    required = set(policy.get("destructive_actions_require_confirmation", []))
    if action not in required:
        return {"ok": True, "status": "pass", "message": "Confirmation is not required.", "required": False}
    if not confirmed:
        return {"ok": False, "status": "fail", "message": "This action requires confirmation.", "required": True, "action": action}
    receipt = confirmation_receipt(config, action, summary=summary or action, affected_paths=affected_paths, reversible=reversible)
    return {"ok": True, "status": "pass", "message": "Confirmation recorded.", "required": True, "receipt": receipt}


def build_permissions_manifest(config: AppConfig, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_security_policy(config)
    writable_dirs = [str((config.root / name).resolve()) for name in policy.get("allowed_runtime_dirs", [])]
    manifest = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "active_project_root": str(config.root),
        "writable_dirs": writable_dirs,
        "read_only_dirs": [str(config.root / "dashboard"), str(config.root / "growth_engine"), str(config.root / "scripts")],
        "protected_dirs": policy.get("protected_dirs", []),
        "enabled_actions": policy.get("allowed_script_actions", []),
        "disabled_actions": [
            "arbitrary_file_access",
            "arbitrary_command_execution",
            "direct_social_posting",
            "cloud_api_calls",
        ],
        "last_validation": utc_now(),
        "warnings": [],
    }
    save_json_file(config.analytics_dir / "permissions_manifest.json", manifest)
    return manifest


def security_summary(config: AppConfig) -> dict[str, Any]:
    report = load_json_file(config.analytics_dir / "security_report.json", {})
    if report:
        return report
    policy = load_security_policy(config)
    project = validate_project_root(config, config.root)
    manifest = build_permissions_manifest(config, policy)
    status = "pass" if project["ok"] else "fail"
    return {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "label": "Secure" if status == "pass" else "Unsafe Configuration",
        "project_root": project,
        "permissions_manifest": manifest,
        "local_only": True,
    }


def write_security_event(config: AppConfig, event_type: str, *, severity: str = "info", summary: dict[str, Any] | None = None) -> None:
    append_event(config, event_type, severity=severity, source="security", summary=summary or {})
    write_audit_event(config, "settings.changed", severity=severity, source="security", summary={"event_type": event_type, **(summary or {})})
