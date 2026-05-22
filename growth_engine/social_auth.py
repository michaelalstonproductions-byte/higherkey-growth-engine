from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


STATUS_PATH = "social_auth_status.json"


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


def instagram_auth_url(config: dict[str, Any], state: str = "higherkey-local") -> str:
    instagram = config.get("instagram", {})
    params = {
        "client_id": os.environ.get(instagram.get("app_id_env", ""), "<meta_app_id>"),
        "redirect_uri": instagram.get("redirect_uri", "http://127.0.0.1:8787/oauth/meta/callback"),
        "scope": ",".join(instagram.get("required_permissions", [])),
        "response_type": "code",
        "state": state,
    }
    return "https://www.facebook.com/dialog/oauth?" + urlencode(params)


def tiktok_auth_url(config: dict[str, Any], state: str = "higherkey-local") -> str:
    tiktok = config.get("tiktok", {})
    params = {
        "client_key": os.environ.get(tiktok.get("client_key_env", ""), "<tiktok_client_key>"),
        "redirect_uri": tiktok.get("redirect_uri", "http://127.0.0.1:8787/oauth/tiktok/callback"),
        "scope": ",".join(tiktok.get("required_scopes", [])),
        "response_type": "code",
        "state": state,
    }
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)


def platform_status(config: dict[str, Any], platform: str) -> dict[str, Any]:
    platform_config = config.get(platform, {})
    if not platform_config or platform_config.get("enabled") is not True:
        return {
            "platform": platform,
            "status": "not_configured",
            "enabled": False,
            "live_api_enabled": False,
            "credentials": {},
            "connected": False,
        }
    if platform == "instagram":
        credentials = {
            "app_id": _redacted_env_status(platform_config.get("app_id_env")),
            "app_secret": _redacted_env_status(platform_config.get("app_secret_env")),
        }
        auth_url = instagram_auth_url(config)
    elif platform == "tiktok":
        credentials = {
            "client_key": _redacted_env_status(platform_config.get("client_key_env")),
            "client_secret": _redacted_env_status(platform_config.get("client_secret_env")),
        }
        auth_url = tiktok_auth_url(config)
    else:
        credentials = {}
        auth_url = ""
    missing = [key for key, value in credentials.items() if not value.get("present")]
    if missing:
        status = "credentials_missing"
    else:
        status = "auth_required"
    return {
        "platform": platform,
        "status": status,
        "enabled": platform_config.get("enabled") is True,
        "mode": platform_config.get("mode", "official_api"),
        "live_api_enabled": platform_config.get("live_api_enabled") is True,
        "credentials": credentials,
        "required_permissions": platform_config.get("required_permissions", []),
        "required_scopes": platform_config.get("required_scopes", []),
        "redirect_uri": platform_config.get("redirect_uri"),
        "auth_url": auth_url,
        "connected": False,
        "token_storage": config.get("storage", {}).get("token_storage", "local_keychain_or_encrypted_file"),
        "token_values_exposed": False,
    }


def check_social_auth_status(config: AppConfig) -> dict[str, Any]:
    connectors = load_connector_config(config.root)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": connectors.get("manual_upload_fallback", True),
        "live_api_enabled_default": connectors.get("live_api_enabled_default", False),
        "token_values_exposed": False,
        "never_commit_tokens": connectors.get("storage", {}).get("never_commit_tokens", True),
        "instagram": platform_status(connectors, "instagram"),
        "tiktok": platform_status(connectors, "tiktok"),
        "notes": [
            "No passwords are accepted or stored.",
            "Token values are not written to analytics or UI logs.",
            "Dry-run/manual mode remains the default when credentials or authorization are missing.",
        ],
    }
    save_json_file(config.analytics_dir / STATUS_PATH, payload)
    return payload


def store_token_metadata(config: AppConfig, platform: str, token_payload: dict[str, Any]) -> dict[str, Any]:
    metadata_path = config.analytics_dir / STATUS_PATH
    existing = load_json_file(metadata_path, default={})
    metadata = {
        "platform": platform,
        "status": "connected" if token_payload else "invalid",
        "stored_at": utc_now(),
        "storage": "local_keychain_or_encrypted_file",
        "token_present": bool(token_payload),
        "token_preview": "redacted",
        "expires_at": token_payload.get("expires_at") if isinstance(token_payload, dict) else None,
    }
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
