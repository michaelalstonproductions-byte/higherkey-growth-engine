from __future__ import annotations

import base64
import json
import os
import platform as platform_module
import subprocess
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


SERVICE = "HigherKey Operator OS Social"
ACCOUNT_PREFIX = "higherkey-social"
STATUS_PATH = "social_token_vault_status.json"
CLIENT_STATUS_PATH = "client_social_token_vault_status.json"
PLATFORMS = ("instagram", "tiktok")
TOKEN_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "id_token",
    "client_secret",
    "app_secret",
    "secret",
    "authorization_code",
    "code",
    "bearer",
    "password",
    "credential",
}
REDACTED = "[REDACTED]"
BEARER_RE = re.compile(r"\bbearer\s+[a-z0-9._~+/-]+=*\b", re.IGNORECASE)


def _security_bin() -> Path:
    return Path("/usr/bin/security")


def keychain_available() -> bool:
    return platform_module.system() == "Darwin" and _security_bin().exists()


def account_name(platform: str) -> str:
    return f"{ACCOUNT_PREFIX}-{platform}"


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return lower in TOKEN_KEYS or any(term in lower for term in ("token", "secret", "password", "credential"))


def redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, nested in value.items():
            safe[key] = REDACTED if _is_sensitive_key(str(key)) and nested else redact_sensitive_value(nested)
        return safe
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, str):
        if BEARER_RE.search(value):
            return BEARER_RE.sub("Bearer [REDACTED]", value)
        return value
    return value


def redact_token_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    safe = redact_sensitive_value(payload or {})
    if not isinstance(safe, dict):
        safe = {"value": REDACTED}
    safe["token_values_exposed"] = False
    return safe


def token_metadata(platform: str, payload: dict[str, Any] | None, storage: str) -> dict[str, Any]:
    scopes = payload.get("scope") or payload.get("scopes") if isinstance(payload, dict) else []
    if isinstance(scopes, str):
        scopes = [item.strip() for item in scopes.replace(",", " ").split() if item.strip()]
    return {
        "platform": platform,
        "status": "connected" if payload and payload.get("access_token") else "invalid",
        "stored_at": utc_now(),
        "storage": storage,
        "token_present": bool(payload and payload.get("access_token")),
        "refresh_token_present": bool(payload and payload.get("refresh_token")),
        "token_preview": REDACTED if payload and payload.get("access_token") else "",
        "expires_at": payload.get("expires_at") if isinstance(payload, dict) else None,
        "scopes": scopes if isinstance(scopes, list) else [],
        "token_values_exposed": False,
    }


def vault_status(config: AppConfig) -> dict[str, Any]:
    metadata_source = load_json_file(config.analytics_dir / "social_auth_status.json", default={})
    metadata = metadata_source.get("token_metadata", {}) if isinstance(metadata_source, dict) else {}
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "client_safe": True,
        "provider": "macos_keychain" if keychain_available() else "not_available",
        "keychain_available": keychain_available(),
        "file_vault_enabled": False,
        "token_values_exposed": False,
        "never_commit_tokens": True,
        "tokens": {
            platform: {
                "platform": platform,
                "account": account_name(platform),
                "metadata_present": bool(metadata.get(platform)),
                "token_present": bool(metadata.get(platform, {}).get("token_present")) if isinstance(metadata.get(platform), dict) else False,
                "token_preview": REDACTED if metadata.get(platform, {}).get("token_present") else "",
                "expires_at": metadata.get(platform, {}).get("expires_at") if isinstance(metadata.get(platform), dict) else None,
                "scopes": metadata.get(platform, {}).get("scopes", []) if isinstance(metadata.get(platform), dict) else [],
                "storage": metadata.get(platform, {}).get("storage", "macos_keychain") if isinstance(metadata.get(platform), dict) else "macos_keychain",
                "token_values_exposed": False,
            }
            for platform in PLATFORMS
        },
        "notes": [
            "Token values are stored only in the local vault provider when explicitly provided.",
            "Analytics files contain metadata only and never contain full token values.",
            "Live posting remains disabled unless connector config, auth, approval, and schedule gates pass.",
        ],
    }
    save_json_file(config.analytics_dir / STATUS_PATH, payload)
    save_json_file(config.analytics_dir / CLIENT_STATUS_PATH, payload)
    return payload


def store_token(config: AppConfig, platform: str, token_payload: dict[str, Any], *, allow_file_fallback: bool = False) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    if not token_payload.get("access_token"):
        raise ValueError("Token payload is missing access_token.")
    serialized = json.dumps(token_payload, sort_keys=True)
    storage = "macos_keychain"
    if keychain_available():
        subprocess.run(
            [
                str(_security_bin()),
                "add-generic-password",
                "-U",
                "-s",
                SERVICE,
                "-a",
                account_name(platform),
                "-w",
                serialized,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif allow_file_fallback and os.environ.get("HIGHERKEY_TOKEN_VAULT_KEY"):
        storage = "local_encrypted_file_placeholder"
        key = os.environ["HIGHERKEY_TOKEN_VAULT_KEY"].encode("utf-8")
        raw = serialized.encode("utf-8")
        encoded = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
        vault_path = config.root / "config" / ".social_token_vault.local"
        vault = load_json_file(vault_path, default={})
        vault[platform] = base64.b64encode(encoded).decode("ascii")
        save_json_file(vault_path, vault)
    else:
        raise RuntimeError("No secure token vault provider is available.")
    metadata_path = config.analytics_dir / "social_auth_status.json"
    existing = load_json_file(metadata_path, default={})
    existing.setdefault("token_metadata", {})[platform] = token_metadata(platform, token_payload, storage)
    existing["token_values_exposed"] = False
    save_json_file(metadata_path, existing)
    return existing["token_metadata"][platform]


def clear_token(config: AppConfig, platform: str) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    removed = False
    if keychain_available():
        result = subprocess.run(
            [str(_security_bin()), "delete-generic-password", "-s", SERVICE, "-a", account_name(platform)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        removed = result.returncode == 0
    vault_path = config.root / "config" / ".social_token_vault.local"
    if vault_path.exists():
        vault = load_json_file(vault_path, default={})
        if platform in vault:
            vault.pop(platform, None)
            save_json_file(vault_path, vault)
            removed = True
    metadata_path = config.analytics_dir / "social_auth_status.json"
    existing = load_json_file(metadata_path, default={})
    if isinstance(existing.get("token_metadata"), dict):
        existing["token_metadata"].pop(platform, None)
        existing["token_values_exposed"] = False
        save_json_file(metadata_path, existing)
    return {"platform": platform, "removed": removed, "token_values_exposed": False}
