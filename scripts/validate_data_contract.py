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
from growth_engine.migrations import load_version_contract
from growth_engine.runtime_db import connect, migrate


def _json_ok(path: Path) -> dict[str, Any]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return {"path": str(path), "status": "pass"}
    except FileNotFoundError:
        return {"path": str(path), "status": "fail", "message": "missing"}
    except json.JSONDecodeError as exc:
        return {"path": str(path), "status": "fail", "message": str(exc)}


def validate(root: Path) -> dict[str, Any]:
    config = load_config(root)
    contract = load_version_contract(config)
    checks: list[dict[str, Any]] = []
    for rel in [
        "config/version_contract.json",
        "config/state_contract.json",
        "config/security_policy.json",
        "config/retention_policy.json",
        "config/client_demo.json",
        "config/project_manifest.example.json",
        "analytics/client_state.json",
        "analytics/client_tasks.json",
        "analytics/client_workflow.json",
        "analytics/client_metrics.json",
        "analytics/client_integrity.json",
        "analytics/client_storage.json",
    ]:
        item = _json_ok(config.root / rel)
        item["name"] = rel
        checks.append(item)
    tables = set()
    try:
        with connect(config) as connection:
            migrate(connection)
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row["name"] for row in rows}
    except Exception as exc:
        checks.append({"name": "runtime_db", "status": "fail", "message": str(exc)})
    for table in contract.get("required_db_tables", []):
        checks.append({"name": f"table:{table}", "status": "pass" if table in tables else "fail"})
    for rel in contract.get("required_scripts", []):
        checks.append({"name": rel, "status": "pass" if (config.root / rel).exists() else "fail"})
    status = "fail" if any(item["status"] == "fail" for item in checks) else "pass"
    report = {"version": 1, "updated_at": utc_now(), "status": status, "local_only": True, "checks": checks}
    save_json_file(config.analytics_dir / "data_contract_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate HigherKey local data contracts.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    report = validate(Path(args.root).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
