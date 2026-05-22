from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import secrets
from typing import Any

from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file
from .social_auth import check_social_auth_status, load_connector_config
from .social_scheduler import load_drafts


POLICY_EXAMPLE = "live_publish_policy.example.json"
POLICY_LOCAL = "live_publish_policy.json"
RECEIPTS_PATH = "live_publish_receipts.json"
STATUS_PATH = "social_live_publish_status.json"
LOG_PATH = "social_live_publish_log.json"
CONFIRMATION_PHRASE = "I understand this will attempt a real platform publish."
RECEIPT_TTL_MINUTES = 30


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


def load_live_publish_policy(root: Path) -> dict[str, Any]:
    local = root / "config" / POLICY_LOCAL
    example = root / "config" / POLICY_EXAMPLE
    policy = load_json_file(local if local.exists() else example, default={})
    policy.setdefault("enable_live_publish_default", False)
    policy.setdefault("require_single_draft_publish", True)
    policy.setdefault("require_explicit_publish_now", True)
    policy.setdefault("require_user_confirmation", True)
    policy.setdefault("allow_bulk_publish", False)
    policy.setdefault("max_live_posts_per_session", 1)
    policy.setdefault("supported_live_platforms", ["instagram_reels", "tiktok"])
    policy.setdefault("unsupported_live_platforms", ["youtube_shorts", "facebook_reels"])
    policy.setdefault("require_due_now", True)
    policy.setdefault("require_connected_account", True)
    policy.setdefault("require_valid_token", True)
    policy.setdefault("require_scope_validation", True)
    policy.setdefault("require_platform_capability_validation", True)
    policy.setdefault("require_publish_readiness_validation", True)
    policy.setdefault("require_manual_confirmation_receipt", True)
    policy.setdefault("confirmation_phrase", CONFIRMATION_PHRASE)
    policy.setdefault("manual_upload_fallback", True)
    policy.setdefault("qa_live_api_calls_allowed", False)
    return policy


def _platform_key(platform: str) -> str:
    return "instagram" if platform == "instagram_reels" else platform


def _draft_by_id(config: AppConfig, draft_id: str | None) -> dict[str, Any] | None:
    if not draft_id:
        return None
    for draft in load_drafts(config):
        if str(draft.get("draft_id") or "") == str(draft_id):
            return draft
    return None


def _due_status(draft: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    scheduled = _parse_time(draft.get("scheduled_for"))
    if policy.get("require_due_now") is True and not scheduled:
        return {"status": "approval_required", "ok": False, "message": "Live publishing requires a scheduled time that is due now."}
    if scheduled and scheduled > _now():
        return {"status": "scheduled_not_due", "ok": False, "message": "This post is scheduled for later and will not publish now."}
    return {"status": "due_now", "ok": True, "message": "Draft is due for live publish validation."}


def _required_scopes_present(platform_status: dict[str, Any], platform_config: dict[str, Any]) -> bool:
    if platform_status.get("status") != "ready_for_live_api":
        return False
    token = platform_status.get("token", {}) if isinstance(platform_status.get("token"), dict) else {}
    scopes = set(token.get("scopes", []) if isinstance(token.get("scopes"), list) else [])
    required = platform_config.get("required_scopes") or platform_config.get("required_permissions") or []
    if not required:
        return True
    return set(required).issubset(scopes)


def validate_live_publish_conditions(
    config: AppConfig,
    *,
    draft_id: str | None = None,
    platform: str | None = None,
    require_receipt: bool = True,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    policy = load_live_publish_policy(config.root)
    draft = _draft_by_id(config, draft_id)
    selected_platform = platform or str(draft.get("platform") if draft else "")
    reasons: list[dict[str, Any]] = []

    if not draft:
        reasons.append({"status": "approval_required", "message": "Live publishing requires a specific draft."})
    if selected_platform in policy.get("unsupported_live_platforms", []):
        reasons.append({"status": "unsupported_platform", "message": "This platform is routed to manual upload."})
    if selected_platform not in policy.get("supported_live_platforms", []):
        reasons.append({"status": "unsupported_platform", "message": "Live publishing is not enabled for this platform."})
    if draft and selected_platform and str(draft.get("platform")) != selected_platform:
        reasons.append({"status": "blocked", "message": "Receipt platform does not match the draft platform."})
    if draft:
        due = _due_status(draft, policy)
        if not due["ok"]:
            reasons.append({"status": due["status"], "message": due["message"]})
        if draft.get("publish_mode") != "live_api":
            reasons.append({"status": "approval_required", "message": "Draft publish_mode must be live_api before live publishing."})

    connectors = load_connector_config(config.root)
    auth = check_social_auth_status(config)
    platform_key = _platform_key(selected_platform)
    platform_config = connectors.get(platform_key, {}) if isinstance(connectors, dict) else {}
    platform_auth = auth.get(platform_key, {}) if isinstance(auth, dict) else {}

    if platform_config.get("enabled") is not True:
        reasons.append({"status": "auth_required", "message": "Official connector is not enabled."})
    if platform_config.get("live_api_enabled") is not True:
        reasons.append({"status": "live_disabled", "message": "Live publishing is disabled for this platform."})
    if platform_auth.get("status") != "ready_for_live_api":
        reasons.append({"status": "auth_required", "message": "Connected account, token, and live readiness are required."})
    if policy.get("require_scope_validation") is True and not _required_scopes_present(platform_auth, platform_config):
        reasons.append({"status": "scope_missing", "message": "Required platform permissions/scopes are not confirmed."})
    capabilities = platform_auth.get("capabilities", {}) if isinstance(platform_auth.get("capabilities"), dict) else {}
    if policy.get("require_platform_capability_validation") is True and not capabilities.get("live_supported_when_ready"):
        reasons.append({"status": "capability_missing", "message": "Platform capability validation is not ready."})
    receipt = validate_live_publish_receipt(config, draft_id=draft_id, platform=selected_platform, receipt_id=receipt_id) if require_receipt else {"valid": True, "status": "receipt_not_required"}
    if require_receipt and not receipt.get("valid"):
        reasons.append({"status": receipt.get("status", "approval_required"), "message": receipt.get("message", "Approval receipt is required.")})

    status = "ready_for_live_api" if not reasons else str(reasons[0].get("status") or "blocked")
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "draft_id": draft_id,
        "platform": selected_platform,
        "status": status,
        "ready": not reasons,
        "reasons": reasons,
        "receipt": receipt,
        "manual_upload_fallback": True,
        "live_call_made": False,
        "token_values_exposed": False,
    }
    save_json_file(config.analytics_dir / STATUS_PATH, payload)
    return payload


def _receipt_digest(draft_id: str, platform: str, approved_at: str) -> str:
    return hashlib.sha256(f"{draft_id}:{platform}:{approved_at}".encode("utf-8")).hexdigest()[:16]


def _load_receipts(config: AppConfig) -> list[dict[str, Any]]:
    payload = load_json_file(config.analytics_dir / RECEIPTS_PATH, default={"receipts": []})
    receipts = payload.get("receipts", []) if isinstance(payload, dict) else []
    return receipts if isinstance(receipts, list) else []


def save_receipts(config: AppConfig, receipts: list[dict[str, Any]]) -> None:
    save_json_file(config.analytics_dir / RECEIPTS_PATH, {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "token_values_exposed": False,
        "count": len(receipts),
        "receipts": receipts[-100:],
    })


def create_live_publish_receipt(
    config: AppConfig,
    *,
    draft_id: str,
    platform: str,
    approved_by: str = "local_operator",
    confirmation_phrase: str = "",
    dry_run_before_live: bool = False,
) -> dict[str, Any]:
    policy = load_live_publish_policy(config.root)
    expected_phrase = policy.get("confirmation_phrase", CONFIRMATION_PHRASE)
    if confirmation_phrase != expected_phrase:
        return {
            "status": "approval_required",
            "valid": False,
            "message": "Live publishing requires the exact confirmation phrase.",
            "token_values_exposed": False,
        }
    draft = _draft_by_id(config, draft_id)
    if not draft or str(draft.get("platform")) != platform:
        return {
            "status": "approval_required",
            "valid": False,
            "message": "Receipt requires a matching draft and platform.",
            "token_values_exposed": False,
        }
    readiness = validate_live_publish_conditions(config, draft_id=draft_id, platform=platform, require_receipt=False)
    approved_at = utc_now()
    receipt = {
        "receipt_id": f"live_{_receipt_digest(draft_id, platform, approved_at)}",
        "draft_id": draft_id,
        "platform": platform,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "expires_at": (_now() + timedelta(minutes=RECEIPT_TTL_MINUTES)).isoformat(),
        "scheduled_for": draft.get("scheduled_for"),
        "publish_mode": draft.get("publish_mode"),
        "token_status": readiness.get("status") if readiness.get("status") in {"auth_required", "scope_missing"} else "redacted_metadata_only",
        "capability_status": "ready" if readiness.get("ready") else readiness.get("status"),
        "live_publish_enabled": readiness.get("ready"),
        "due_status": "due_now" if not any(item.get("status") == "scheduled_not_due" for item in readiness.get("reasons", [])) else "scheduled_not_due",
        "confirmation_phrase_used": True,
        "dry_run_before_live": bool(dry_run_before_live),
        "manual_upload_fallback_available": True,
        "status": "approved" if readiness.get("status") not in {"approval_required", "scheduled_not_due", "unsupported_platform"} else "approved_pending_readiness",
        "token_values_exposed": False,
    }
    receipts = _load_receipts(config)
    receipts.append(receipt)
    save_receipts(config, receipts)
    return {"status": receipt["status"], "valid": True, "receipt": receipt, "readiness": readiness, "token_values_exposed": False}


def validate_live_publish_receipt(config: AppConfig, *, draft_id: str | None, platform: str | None, receipt_id: str | None = None) -> dict[str, Any]:
    receipts = _load_receipts(config)
    matches = [
        item for item in receipts
        if isinstance(item, dict)
        and str(item.get("draft_id")) == str(draft_id)
        and str(item.get("platform")) == str(platform)
        and (not receipt_id or str(item.get("receipt_id")) == str(receipt_id))
    ]
    if not matches:
        return {"status": "approval_required", "valid": False, "message": "Live publishing requires an approval receipt.", "token_values_exposed": False}
    receipt = matches[-1]
    expires_at = _parse_time(receipt.get("expires_at"))
    if not expires_at or expires_at <= _now():
        return {"status": "approval_required", "valid": False, "message": "Live publish approval receipt expired.", "receipt_id": receipt.get("receipt_id"), "token_values_exposed": False}
    if receipt.get("confirmation_phrase_used") is not True:
        return {"status": "approval_required", "valid": False, "message": "Approval receipt is missing the confirmation phrase.", "receipt_id": receipt.get("receipt_id"), "token_values_exposed": False}
    return {"status": "valid_receipt", "valid": True, "receipt_id": receipt.get("receipt_id"), "token_values_exposed": False}


def live_publish_readiness_summary(config: AppConfig, *, platform: str | None = None) -> dict[str, Any]:
    drafts = load_drafts(config)
    if not (config.analytics_dir / RECEIPTS_PATH).exists():
        save_receipts(config, [])
    items = []
    for draft in drafts:
        if platform and platform != "all" and draft.get("platform") != platform:
            continue
        if draft.get("publish_mode") != "live_api":
            continue
        items.append(validate_live_publish_conditions(config, draft_id=str(draft.get("draft_id")), platform=str(draft.get("platform")), require_receipt=False))
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "dry_run": True,
        "manual_upload_fallback": True,
        "live_call_made": False,
        "count": len(items),
        "ready_count": sum(1 for item in items if item.get("ready")),
        "blocked_count": sum(1 for item in items if not item.get("ready")),
        "items": items,
        "token_values_exposed": False,
    }
    save_json_file(config.analytics_dir / "live_publish_readiness.json", payload)
    save_json_file(config.analytics_dir / "client_live_publish_readiness.json", payload)
    return payload


def append_live_publish_log(config: AppConfig, entry: dict[str, Any]) -> None:
    existing = load_json_file(config.analytics_dir / LOG_PATH, default={"runs": []})
    runs = existing.get("runs", []) if isinstance(existing, dict) and isinstance(existing.get("runs"), list) else []
    runs.append(entry)
    save_json_file(config.analytics_dir / LOG_PATH, {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_fallback": True,
        "live_call_made": any(bool(item.get("live_call_made")) for item in runs if isinstance(item, dict)),
        "runs": runs[-100:],
    })
