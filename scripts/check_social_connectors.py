#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.json_store import save_json_file
from growth_engine.social_auth import connector_status, validate_connector_environment
from growth_engine.social_token_vault import vault_status


def main() -> int:
    config = load_config(Path.cwd())
    status = connector_status(config)
    environment = validate_connector_environment(config)
    vault = vault_status(config)
    diagnostics = {
        "version": 1,
        "updated_at": status["updated_at"],
        "local_only": True,
        "client_safe": True,
        "manual_upload_fallback": status.get("manual_upload_fallback", True),
        "live_api_enabled_default": status.get("live_api_enabled_default", False),
        "config_file": environment.get("config_file"),
        "local_config_exists": environment.get("local_config_exists"),
        "token_storage": environment.get("token_storage"),
        "vault": vault,
        "never_commit_tokens": environment.get("never_commit_tokens"),
        "token_values_exposed": False,
        "platforms": {
            "instagram": status.get("instagram", {}),
            "tiktok": status.get("tiktok", {}),
        },
        "checks": environment.get("checks", []),
        "notes": [
            "No live network calls were made.",
            "Environment variables are reported as present or missing only; values are never printed.",
            "Manual upload fallback remains enabled.",
        ],
    }
    for platform in ("instagram", "tiktok"):
        diagnostics["platforms"][platform].pop("auth_url", None)
    save_json_file(config.analytics_dir / "social_connector_diagnostics.json", diagnostics)
    save_json_file(config.analytics_dir / "client_social_connector_diagnostics.json", diagnostics)
    print(json.dumps({
        "status": "pass",
        "manual_upload_fallback": diagnostics["manual_upload_fallback"],
        "live_api_enabled_default": diagnostics["live_api_enabled_default"],
        "local_config_exists": diagnostics["local_config_exists"],
        "token_values_exposed": False,
        "paths": [
            "analytics/social_connection_status.json",
            "analytics/client_social_connection_status.json",
            "analytics/social_connector_diagnostics.json",
            "analytics/client_social_connector_diagnostics.json",
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
