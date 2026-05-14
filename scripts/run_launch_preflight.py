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
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.migrations import build_upgrade_plan
from growth_engine.runtime_db import connect, migrate
from growth_engine.security import validate_project_root


def _normalize_version(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = [part for part in text.split(".") if part != ""]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:3])


def preflight(root: Path) -> dict[str, Any]:
    config = load_config(root)
    checks: list[dict[str, Any]] = []
    checks.append({"name": "project_manifest", "status": "pass" if (config.root / "config" / "project_manifest.json").exists() else "warn"})
    project = validate_project_root(config, config.root)
    checks.append({"name": "project_root", "status": project["status"], "message": project["message"]})
    try:
        with connect(config) as connection:
            migrate(connection)
        checks.append({"name": "runtime_db", "status": "pass"})
    except Exception as exc:
        checks.append({"name": "runtime_db", "status": "fail", "message": str(exc)})
    pkg = load_json_file(config.root / "package.json", {})
    release = load_json_file(config.root / "config" / "release.json", {})
    package_version = _normalize_version(pkg.get("version"))
    release_version = _normalize_version(release.get("version"))
    checks.append({"name": "version_match", "status": "pass" if package_version == release_version else "warn", "package": pkg.get("version"), "release": release.get("version")})
    upgrade = build_upgrade_plan(config)
    checks.append({"name": "upgrade_plan", "status": "pass" if upgrade["status"] != "fail" else "fail", "migrations": len(upgrade.get("migrations", []))})
    for name, rel in (
        ("security", "analytics/security_report.json"),
        ("storage", "analytics/client_storage.json"),
        ("reconciliation", "analytics/client_integrity.json"),
        ("client_state", "analytics/client_state.json"),
        ("worker", "analytics/worker_runtime_status.json"),
    ):
        payload = load_json_file(config.root / rel, {})
        checks.append({"name": name, "status": "pass" if payload else "warn"})
    lock = config.analytics_dir / "runtime.lock"
    checks.append({"name": "runtime_lock", "status": "warn" if lock.exists() else "pass", "path": str(lock)})
    status = "fail" if any(item["status"] == "fail" for item in checks) else ("warn" if any(item["status"] == "warn" for item in checks) else "pass")
    report = {"version": 1, "updated_at": utc_now(), "status": status, "local_only": True, "checks": checks}
    save_json_file(config.analytics_dir / "launch_preflight.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey launch preflight checks.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    report = preflight(Path(args.root).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
