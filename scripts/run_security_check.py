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

from growth_engine.config import ensure_directories, load_config
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file
from growth_engine.security import (
    build_permissions_manifest,
    load_security_policy,
    read_local_api_token,
    require_confirmation,
    security_summary,
    validate_import_file,
    validate_project_root,
    validate_runtime_path,
    validate_script_action,
    write_security_event,
)


def _status(checks: list[dict[str, Any]]) -> str:
    if any(item.get("status") == "fail" for item in checks):
        return "fail"
    if any(item.get("status") == "warn" for item in checks):
        return "warn"
    return "pass"


def run_security_check(root: Path, *, fixture_receipt: bool = False) -> dict[str, Any]:
    config = load_config(root)
    ensure_directories(config)
    policy = load_security_policy(config)
    checks: list[dict[str, Any]] = []

    checks.append({"name": "security_policy_load", "status": "pass", "path": "config/security_policy.json", "local_only": bool(policy.get("local_only"))})
    project_check = validate_project_root(config, config.root)
    checks.append({"name": "active_project_root", "status": project_check["status"], "message": project_check["message"], "path": str(config.root)})
    inbox_check = validate_project_root(config, config.inbox_dir)
    checks.append({"name": "content_inbox_root_rejection", "status": "pass" if not inbox_check["ok"] else "fail", "message": inbox_check["message"]})
    protected_check = validate_project_root(config, Path("/"))
    checks.append({"name": "protected_root_rejection", "status": "pass" if not protected_check["ok"] else "fail", "message": protected_check["message"]})

    for folder in policy.get("allowed_runtime_dirs", []):
        runtime_check = validate_runtime_path(config, config.root / folder)
        checks.append({"name": f"runtime_dir_{folder}", "status": runtime_check["status"], "path": runtime_check.get("path")})

    allowed_hosts = set(policy.get("allowed_api_hosts", []))
    checks.append({"name": "local_api_hosts", "status": "pass" if {"127.0.0.1", "localhost"}.issubset(allowed_hosts) else "fail", "allowed_hosts": sorted(allowed_hosts)})
    checks.append({"name": "local_api_token_state", "status": "pass", "enabled": bool(policy.get("local_api_auth_enabled")), "token_present": bool(read_local_api_token(config))})
    checks.append({"name": "arbitrary_file_access_disabled", "status": "pass" if not policy.get("allow_arbitrary_file_access") else "fail"})
    checks.append({"name": "arbitrary_command_execution_disabled", "status": "pass" if not policy.get("allow_arbitrary_command_execution") else "fail"})

    for action in ("run_pipeline", "repair_project_media", "maintenance", "backup_project", "reconcile_apply"):
        action_check = validate_script_action(config, action)
        checks.append({"name": f"script_action_{action}", "status": action_check["status"], "message": action_check["message"]})

    blocked_import = validate_import_file(config, config.root / "README.md")
    checks.append({"name": "import_extension_rejection", "status": "pass" if not blocked_import["ok"] else "fail", "message": blocked_import["message"]})

    receipt = None
    if fixture_receipt:
        confirmation = require_confirmation(
            config,
            "backup_project",
            confirmed=True,
            summary="QA/security confirmation receipt fixture.",
            affected_paths=["out/project_backups"],
            reversible=True,
        )
        receipt = confirmation.get("receipt")
        checks.append({"name": "confirmation_receipt_fixture", "status": confirmation["status"], "required": confirmation.get("required")})

    manifest = build_permissions_manifest(config, policy)
    status = _status(checks)
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "label": "Secure" if status == "pass" else ("Needs Attention" if status == "warn" else "Unsafe Configuration"),
        "local_only": True,
        "checks": checks,
        "policy_summary": {
            "allowed_import_extensions": policy.get("allowed_import_extensions", []),
            "max_import_file_size_mb": policy.get("max_import_file_size_mb"),
            "local_api_auth_enabled": policy.get("local_api_auth_enabled", False),
            "destructive_actions_require_confirmation": policy.get("destructive_actions_require_confirmation", []),
        },
        "permissions_manifest_path": str(config.analytics_dir / "permissions_manifest.json"),
        "confirmation_receipt": receipt,
    }
    save_json_file(config.analytics_dir / "security_report.json", report)
    write_security_event(config, "security.check_completed", severity=status, summary={"status": status})
    return {"security_report": report, "permissions_manifest": manifest, "summary": security_summary(config)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey local security checks.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--fixture-receipt", action="store_true", help="Write a harmless confirmation receipt fixture.")
    args = parser.parse_args()
    payload = run_security_check(Path(args.root).resolve(), fixture_receipt=args.fixture_receipt)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["security_report"]["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
