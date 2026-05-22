from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .oauth_state import create_oauth_state, oauth_state_status
from .social_token_vault import token_metadata, vault_status


STATUS_PATH = "social_auth_status.json"
CONNECTION_STATUS_PATH = "social_connection_status.json"
CLIENT_CONNECTION_STATUS_PATH = "client_social_connection_status.json"
PLATFORMS = ("instagram", "tiktok")

PLATFORM_CAPABILITIES = {
    "instagram": {
        "official_api": "Meta Instagram Platform content publishing",
        "content_types": ["reels"],
        "requires": ["instagram_business_basic", "instagram_business_content_publish", "professional_account", "hosted_media_or_supported_upload"],
        "manual_upload_fallback": True,
        "live_posting_default": False,
    },
    "tiktok": {
        "official_api": "TikTok Content Posting API",
        "content_types": ["video"],
        "requires": ["registered_app", "content_posting_api_product", "video.publish", "user_authorization"],
        "manual_upload_fallback": True,
        "live_posting_default": False,
        "caveat": "Unaudited clients may be private-post restricted.",
    },
}


def connector_config_path(root: Path) -> Path:
    local = root / "config" / "social_connectors.json"
    if local.exists():
        return local
    return root / "config" / "social_connectors.example.json"


def load_connector_config(root: Path) -> dict[str, Any]:
    return load_json_file(connector_config_path(root), default={})


def _env_present(name: str | None) -> bool:
    return bool(name and os.environ.get(name))


def _redacted_env_status(name: str | None) -> dict[str, Any]:
    return {"env": name or "", "present": _env_present(name)}


def _status_file(config: AppConfig) -> dict[str, Any]:
    return load_json_file(config.analytics_dir / STATUS_PATH, default={})


def redacted_token_status(config: AppConfig, platform: str) -> dict[str, Any]:
    metadata = _status_file(config).get("token_metadata", {})
    platform_metadata = metadata.get(platform, {}) if isinstance(metadata, dict) else {}
    status = str(platform_metadata.get("status") or "not_configured")
    if not platform_metadata:
        status = "not_configured"
    return {
        "platform": platform,
        "status": status,
        "token_present": bool(platform_metadata.get("token_present")),
        "token_preview": "redacted" if platform_metadata.get("token_present") else "",
        "expires_at": platform_metadata.get("expires_at"),
        "storage": platform_metadata.get("storage", "local_keychain_or_encrypted_file"),
        "token_values_exposed": False,
    }


def platform_capability_status(config: dict[str, Any], platform: str) -> dict[str, Any]:
    platform_config = config.get(platform, {})
    capabilities = PLATFORM_CAPABILITIES.get(platform, {})
    requirements = platform_config.get("required_permissions") or platform_config.get("required_scopes") or capabilities.get("requires", [])
    return {
        "platform": platform,
        "mode": platform_config.get("mode", "official_api"),
        "official_api": capabilities.get("official_api", "official_api"),
        "content_types": capabilities.get("content_types", []),
        "requirements": requirements,
        "required_permissions": platform_config.get("required_permissions", []),
        "required_scopes": platform_config.get("required_scopes", []),
        "manual_upload_fallback": config.get("manual_upload_fallback", True),
        "dry_run_supported": True,
        "live_supported_when_ready": platform in PLATFORMS,
        "live_posting_default": False,
        "live_api_enabled": platform_config.get("live_api_enabled") is True,
        "caveat": capabilities.get("caveat", ""),
    }


def instagram_auth_url(config: dict[str, Any], state: str) -> str:
    instagram = config.get("instagram", {})
    params = {
        "client_id": os.environ.get(instagram.get("app_id_env", ""), "<meta_app_id>"),
        "redirect_uri": instagram.get("redirect_uri", "http://127.0.0.1:8787/oauth/meta/callback"),
        "scope": ",".join(instagram.get("required_permissions", [])),
        "response_type": "code",
        "state": state,
    }
    return "https://www.facebook.com/dialog/oauth?" + urlencode(params)


def tiktok_auth_url(config: dict[str, Any], state: str) -> str:
    tiktok = config.get("tiktok", {})
    params = {
        "client_key": os.environ.get(tiktok.get("client_key_env", ""), "<tiktok_client_key>"),
        "redirect_uri": tiktok.get("redirect_uri", "http://127.0.0.1:8787/oauth/tiktok/callback"),
        "scope": ",".join(tiktok.get("required_scopes", [])),
        "response_type": "code",
        "state": state,
    }
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)


def platform_auth_url(config: dict[str, Any], platform: str, app_config: AppConfig) -> str:
    state = create_oauth_state(app_config, platform)["state"]
    if platform == "instagram":
        return instagram_auth_url(config, state)
    if platform == "tiktok":
        return tiktok_auth_url(config, state)
    return ""


def platform_status(config: dict[str, Any], platform: str, app_config: AppConfig | None = None) -> dict[str, Any]:
    platform_config = config.get(platform, {})
    if not platform_config or platform_config.get("enabled") is not True:
        return {
            "platform": platform,
            "status": "not_configured",
            "enabled": False,
            "live_api_enabled": False,
            "credentials": {},
            "connected": False,
            "readiness": "ready_for_manual_upload",
            "manual_upload_fallback": config.get("manual_upload_fallback", True),
            "token": {"status": "not_configured", "token_values_exposed": False},
            "capabilities": platform_capability_status(config, platform),
        }
    if platform == "instagram":
        credentials = {
            "app_id": _redacted_env_status(platform_config.get("app_id_env")),
            "app_secret": _redacted_env_status(platform_config.get("app_secret_env")),
        }
        auth_url = platform_auth_url(config, platform, app_config) if app_config else ""
    elif platform == "tiktok":
        credentials = {
            "client_key": _redacted_env_status(platform_config.get("client_key_env")),
            "client_secret": _redacted_env_status(platform_config.get("client_secret_env")),
        }
        auth_url = platform_auth_url(config, platform, app_config) if app_config else ""
    else:
        credentials = {}
        auth_url = ""
    token = redacted_token_status(app_config, platform) if app_config else {"status": "not_configured", "token_values_exposed": False}
    missing = [key for key, value in credentials.items() if not value.get("present")]
    live_enabled = platform_config.get("live_api_enabled") is True
    connected = token.get("status") == "connected" and not missing
    if missing:
        status = "credentials_missing"
    elif token.get("status") in {"expired", "invalid"}:
        status = str(token.get("status"))
    elif connected and live_enabled:
        status = "ready_for_live_api"
    elif connected:
        status = "live_disabled"
    elif not live_enabled:
        status = "dry_run_only"
    else:
        status = "auth_required"
    return {
        "platform": platform,
        "status": status,
        "enabled": platform_config.get("enabled") is True,
        "mode": platform_config.get("mode", "official_api"),
        "live_api_enabled": live_enabled,
        "credentials": credentials,
        "missing_credentials": missing,
        "required_permissions": platform_config.get("required_permissions", []),
        "required_scopes": platform_config.get("required_scopes", []),
        "redirect_uri": platform_config.get("redirect_uri"),
        "auth_url": auth_url,
        "connected": connected,
        "token_storage": config.get("storage", {}).get("token_storage", "local_keychain_or_encrypted_file"),
        "token": token,
        "capabilities": platform_capability_status(config, platform),
        "token_values_exposed": False,
        "readiness": "ready_for_live_api" if status == "ready_for_live_api" else "ready_for_manual_upload",
        "manual_upload_fallback": config.get("manual_upload_fallback", True),
        "last_checked": utc_now(),
    }


def validate_connector_environment(config: AppConfig) -> dict[str, Any]:
    connectors = load_connector_config(config.root)
    local_config = config.root / "config" / "social_connectors.json"
    vault = vault_status(config)
    checks = []
    for platform in PLATFORMS:
        platform_config = connectors.get(platform, {})
        env_names = []
        if platform == "instagram":
            env_names = [platform_config.get("app_id_env"), platform_config.get("app_secret_env")]
        if platform == "tiktok":
            env_names = [platform_config.get("client_key_env"), platform_config.get("client_secret_env")]
        checks.append({
            "platform": platform,
            "enabled": platform_config.get("enabled") is True,
            "mode": platform_config.get("mode", "official_api"),
            "environment": [_redacted_env_status(name) for name in env_names if name],
            "redirect_uri": platform_config.get("redirect_uri", ""),
            "live_api_enabled": platform_config.get("live_api_enabled") is True,
        })
    return {
        "local_only": True,
        "config_file": "config/social_connectors.json" if local_config.exists() else "config/social_connectors.example.json",
        "local_config_exists": local_config.exists(),
        "manual_upload_fallback": connectors.get("manual_upload_fallback", True),
        "live_api_enabled_default": connectors.get("live_api_enabled_default", False),
        "token_storage": connectors.get("storage", {}).get("token_storage", "local_keychain_or_encrypted_file"),
        "never_commit_tokens": connectors.get("storage", {}).get("never_commit_tokens", True),
        "vault": vault,
        "oauth_state": oauth_state_status(config),
        "checks": checks,
    }


def connector_readiness_summary(statuses: dict[str, Any]) -> dict[str, Any]:
    platform_statuses = [statuses.get(platform, {}) for platform in PLATFORMS]
    return {
        "manual_upload_ready": True,
        "dry_run_ready": True,
        "live_ready_count": sum(1 for item in platform_statuses if item.get("status") == "ready_for_live_api"),
        "auth_required_count": sum(1 for item in platform_statuses if item.get("status") in {"auth_required", "dry_run_only", "live_disabled"}),
        "credentials_missing_count": sum(1 for item in platform_statuses if item.get("status") == "credentials_missing"),
        "not_configured_count": sum(1 for item in platform_statuses if item.get("status") == "not_configured"),
        "manual_upload_fallback": statuses.get("manual_upload_fallback", True),
        "live_api_enabled_default": statuses.get("live_api_enabled_default", False),
        "vault_ready": bool(statuses.get("vault", {}).get("keychain_available")),
    }


def client_safe_status(payload: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(payload))
    for platform in PLATFORMS:
        item = safe.get(platform, {})
        item.pop("auth_url", None)
        credentials = item.get("credentials", {})
        for credential in credentials.values():
            if isinstance(credential, dict):
                credential.pop("value", None)
        token = item.get("token", {})
        if isinstance(token, dict):
            token["token_preview"] = "redacted" if token.get("token_present") else ""
            token["token_values_exposed"] = False
    safe["client_safe"] = True
    safe["token_values_exposed"] = False
    return safe


def connector_status(config: AppConfig) -> dict[str, Any]:
    connectors = load_connector_config(config.root)
    existing_status = _status_file(config)
    vault = vault_status(config)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": connectors.get("manual_upload_fallback", True),
        "live_api_enabled_default": connectors.get("live_api_enabled_default", False),
        "token_values_exposed": False,
        "never_commit_tokens": connectors.get("storage", {}).get("never_commit_tokens", True),
        "environment": validate_connector_environment(config),
        "vault": vault,
        "instagram": platform_status(connectors, "instagram", config),
        "tiktok": platform_status(connectors, "tiktok", config),
        "notes": [
            "HigherKey uses official platform APIs only.",
            "Manual upload is always available.",
            "No passwords are accepted or stored.",
            "Token values are redacted and are not written to client status files.",
        ],
    }
    if isinstance(existing_status.get("token_metadata"), dict):
        payload["token_metadata"] = existing_status["token_metadata"]
    payload["summary"] = connector_readiness_summary(payload)
    save_json_file(config.analytics_dir / CONNECTION_STATUS_PATH, payload)
    save_json_file(config.analytics_dir / CLIENT_CONNECTION_STATUS_PATH, client_safe_status(payload))
    save_json_file(config.analytics_dir / STATUS_PATH, payload)
    return payload


def check_social_auth_status(config: AppConfig) -> dict[str, Any]:
    return connector_status(config)


def store_token_metadata(config: AppConfig, platform: str, token_payload: dict[str, Any]) -> dict[str, Any]:
    metadata_path = config.analytics_dir / STATUS_PATH
    existing = load_json_file(metadata_path, default={})
    metadata = token_metadata(platform, token_payload, "local_keychain_or_encrypted_file")
    existing.setdefault("token_metadata", {})[platform] = metadata
    existing["token_values_exposed"] = False
    save_json_file(metadata_path, existing)
    return metadata


def main() -> None:
    from .config import load_config

    config = load_config(Path.cwd())
    print(json.dumps(check_social_auth_status(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
