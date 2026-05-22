#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file
from growth_engine.oauth_state import oauth_state_status
from growth_engine.social_auth import connector_status, load_connector_config, platform_capability_status
from growth_engine.social_token_vault import vault_status


def readiness_for_platform(connectors: dict, status: dict, platform: str) -> dict:
    platform_config = connectors.get(platform, {})
    platform_status = status.get(platform, {})
    capabilities = platform_capability_status(connectors, platform)
    required = platform_config.get("required_permissions") or platform_config.get("required_scopes") or []
    token_scopes = platform_status.get("token", {}).get("scopes", [])
    if isinstance(token_scopes, str):
        token_scopes = [item.strip() for item in token_scopes.replace(",", " ").split() if item.strip()]
    missing_permissions = sorted(set(required) - set(token_scopes)) if token_scopes else list(required)
    enabled = platform_config.get("enabled") is True
    credentials_missing = platform_status.get("status") == "credentials_missing"
    connected = platform_status.get("connected") is True
    live_enabled = platform_config.get("live_api_enabled") is True
    ready_for_dry_run = True
    ready_for_live_api = enabled and connected and live_enabled and not credentials_missing and not missing_permissions
    return {
        "platform": platform,
        "enabled": enabled,
        "status": platform_status.get("status", "not_configured"),
        "official_api": capabilities.get("official_api"),
        "required_permissions": platform_config.get("required_permissions", []),
        "required_scopes": platform_config.get("required_scopes", []),
        "granted_scopes_redacted": token_scopes,
        "missing_permissions_or_scopes": missing_permissions,
        "credentials_missing": credentials_missing,
        "connected": connected,
        "live_api_enabled": live_enabled,
        "ready_for_dry_run": ready_for_dry_run,
        "ready_for_manual_upload": True,
        "ready_for_live_api": ready_for_live_api,
        "live_blocked_reason": "" if ready_for_live_api else "Official OAuth, token vault, required permissions/scopes, and live mode must all be ready.",
        "manual_upload_fallback": True,
        "token_values_exposed": False,
    }


def main() -> int:
    config = load_config(Path.cwd())
    connectors = load_connector_config(config.root)
    status = connector_status(config)
    vault = vault_status(config)
    state_status = oauth_state_status(config)
    platforms = {
        platform: readiness_for_platform(connectors, status, platform)
        for platform in ("instagram", "tiktok")
    }
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "client_safe": True,
        "manual_upload_fallback": True,
        "live_api_enabled_default": connectors.get("live_api_enabled_default", False),
        "live_posting_enabled_by_default": False,
        "dry_run_ready": True,
        "live_call_made": False,
        "token_values_exposed": False,
        "vault": vault,
        "oauth_state": state_status,
        "platforms": platforms,
        "summary": {
            "ready_for_live_api_count": sum(1 for item in platforms.values() if item["ready_for_live_api"]),
            "auth_required_count": sum(1 for item in platforms.values() if item["status"] in {"auth_required", "dry_run_only", "live_disabled"}),
            "credentials_missing_count": sum(1 for item in platforms.values() if item["credentials_missing"]),
            "manual_upload_ready": True,
            "dry_run_ready": True,
        },
    }
    save_json_file(config.analytics_dir / "social_oauth_readiness.json", payload)
    save_json_file(config.analytics_dir / "client_social_oauth_readiness.json", payload)
    print(json.dumps({
        "status": "pass",
        "dry_run_ready": True,
        "live_call_made": False,
        "token_values_exposed": False,
        "ready_for_live_api_count": payload["summary"]["ready_for_live_api_count"],
        "paths": [
            "analytics/social_oauth_readiness.json",
            "analytics/client_social_oauth_readiness.json",
            "analytics/social_token_vault_status.json",
            "analytics/client_social_token_vault_status.json",
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
