from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


STATE_PATH = "oauth_state_status.json"
CLIENT_STATE_PATH = "client_oauth_state_status.json"
STATE_TTL_MINUTES = 15
PLATFORMS = {"instagram", "tiktok", "dry_run", "callback"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _path(config: AppConfig):
    return config.analytics_dir / STATE_PATH


def _client_path(config: AppConfig):
    return config.analytics_dir / CLIENT_STATE_PATH


def _load(config: AppConfig) -> dict[str, Any]:
    payload = load_json_file(_path(config), default={"states": []})
    states = payload.get("states", []) if isinstance(payload, dict) else []
    payload["states"] = states if isinstance(states, list) else []
    return payload


def _client_safe(payload: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "client_safe": True,
        "token_values_exposed": False,
        "pending_count": sum(1 for item in payload.get("states", []) if item.get("status") == "pending"),
        "states": [
            {
                "platform": item.get("platform"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "expires_at": item.get("expires_at"),
                "validated_at": item.get("validated_at"),
                "expired_at": item.get("expired_at"),
                "state_present": bool(item.get("state")),
                "state_preview": "redacted" if item.get("state") else "",
            }
            for item in payload.get("states", [])
        ][-20:],
    }
    return safe


def _save(config: AppConfig, payload: dict[str, Any]) -> None:
    payload["version"] = 1
    payload["updated_at"] = utc_now()
    payload["local_only"] = True
    payload["token_values_exposed"] = False
    save_json_file(_path(config), payload)
    save_json_file(_client_path(config), _client_safe(payload))


def expire_old_oauth_states(config: AppConfig) -> dict[str, Any]:
    payload = _load(config)
    now = _now()
    expired = 0
    for item in payload["states"]:
        if item.get("status") != "pending":
            continue
        expires_at = _parse_time(item.get("expires_at"))
        if not expires_at or expires_at <= now:
            item["status"] = "expired"
            item["expired_at"] = utc_now()
            expired += 1
    payload["states"] = payload["states"][-100:]
    _save(config, payload)
    return {"status": "pass", "expired_count": expired, "token_values_exposed": False}


def create_oauth_state(config: AppConfig, platform: str, *, ttl_minutes: int = STATE_TTL_MINUTES) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported OAuth platform: {platform}")
    expire_old_oauth_states(config)
    payload = _load(config)
    state = secrets.token_urlsafe(32)
    created_at = _now()
    record = {
        "platform": platform,
        "state": state,
        "status": "pending",
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=ttl_minutes)).isoformat(),
        "token_values_exposed": False,
    }
    payload["states"].append(record)
    _save(config, payload)
    return {
        "platform": platform,
        "state": state,
        "status": "pending",
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
        "token_values_exposed": False,
    }


def validate_oauth_state(config: AppConfig, platform: str, received_state: str | None) -> dict[str, Any]:
    expire_old_oauth_states(config)
    payload = _load(config)
    if not received_state:
        result = {
            "platform": platform,
            "status": "missing_state",
            "valid": False,
            "message": "OAuth callback is missing state and was rejected.",
            "token_values_exposed": False,
        }
        _save(config, payload)
        return result
    matching = [
        item
        for item in payload["states"]
        if item.get("platform") == platform and item.get("state") == received_state
    ]
    for item in matching:
        if item.get("status") == "expired":
            _save(config, payload)
            return {
                "platform": platform,
                "status": "expired_state",
                "valid": False,
                "message": "OAuth callback state is expired and was rejected.",
                "token_values_exposed": False,
            }
        if item.get("status") != "pending":
            continue
        expires_at = _parse_time(item.get("expires_at"))
        if not expires_at or expires_at <= _now():
            item["status"] = "expired"
            item["expired_at"] = utc_now()
            _save(config, payload)
            return {
                "platform": platform,
                "status": "expired_state",
                "valid": False,
                "message": "OAuth callback state is expired and was rejected.",
                "token_values_exposed": False,
            }
        item["status"] = "validated"
        item["validated_at"] = utc_now()
        _save(config, payload)
        return {
            "platform": platform,
            "status": "valid_state",
            "valid": True,
            "message": "OAuth callback state validated.",
            "token_values_exposed": False,
        }
    _save(config, payload)
    return {
        "platform": platform,
        "status": "invalid_state",
        "valid": False,
        "message": "OAuth callback state does not match a pending local state and was rejected.",
        "token_values_exposed": False,
    }


def oauth_state_status(config: AppConfig) -> dict[str, Any]:
    expire_old_oauth_states(config)
    payload = _load(config)
    safe = _client_safe(payload)
    save_json_file(_client_path(config), safe)
    return safe
