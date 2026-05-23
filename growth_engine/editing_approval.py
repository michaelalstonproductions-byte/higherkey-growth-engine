from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .editing_manifest import build_editing_manifest, verify_editing_safety
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


APPROVAL_SCOPES = {"preview_only", "final_render", "edited_social_export"}


def _analytics(config: AppConfig, name: str) -> Path:
    return config.analytics_dir / name


def _load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_json_file(path, default or {})


def _receipt_id(asset_id: str, scope: str, approved_at: str) -> str:
    basis = f"{asset_id}|{scope}|{approved_at}"
    return "edit_receipt_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _approval_id(asset: dict[str, Any]) -> str:
    basis = "|".join([str(asset.get("asset_id") or ""), str(asset.get("plan_id") or ""), str(asset.get("platform") or "")])
    return "edit_approval_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _receipt_expired(receipt: dict[str, Any]) -> bool:
    expires_at = _parse_time(receipt.get("expires_at"))
    if expires_at is None:
        return False
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _receipts(config: AppConfig) -> list[dict[str, Any]]:
    payload = _load(_analytics(config, "editing_approval_receipts.json"), {"receipts": []})
    receipts = payload.get("receipts", [])
    return receipts if isinstance(receipts, list) else []


def _rejections(config: AppConfig) -> list[dict[str, Any]]:
    payload = _load(_analytics(config, "editing_rejection_log.json"), {"rejections": []})
    rejections = payload.get("rejections", [])
    return rejections if isinstance(rejections, list) else []


def matching_receipt(asset: dict[str, Any], scope: str, receipts: list[dict[str, Any]] | None = None, config: AppConfig | None = None) -> dict[str, Any] | None:
    receipt_list = receipts if receipts is not None else (_receipts(config) if config else [])
    for receipt in reversed(receipt_list):
        if receipt.get("asset_id") != asset.get("asset_id"):
            continue
        if receipt.get("plan_id") != asset.get("plan_id"):
            continue
        if str(receipt.get("platform")) != str(asset.get("platform")):
            continue
        if receipt.get("approval_scope") != scope:
            continue
        if receipt.get("original_media_protected") is not True:
            continue
        if receipt.get("source_overwrite_allowed") is True:
            continue
        if receipt.get("status") not in {None, "approved", "pass"}:
            continue
        if _receipt_expired(receipt):
            continue
        return receipt
    return None


def has_approval_receipt(asset: dict[str, Any], scope: str, config: AppConfig) -> bool:
    return matching_receipt(asset, scope, config=config) is not None


def _rejection_for(asset: dict[str, Any], rejections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(rejections):
        if item.get("asset_id") == asset.get("asset_id") and item.get("status") in {"rejected", "needs_revision"}:
            return item
    return None


def _queue_status(asset: dict[str, Any], receipts: list[dict[str, Any]], rejections: list[dict[str, Any]]) -> str:
    rejection = _rejection_for(asset, rejections)
    if rejection:
        return str(rejection.get("status"))
    if matching_receipt(asset, "edited_social_export", receipts=receipts):
        return "export_ready" if asset.get("status") in {"export_ready", "final_rendered"} else "approved"
    if matching_receipt(asset, "final_render", receipts=receipts):
        return "approved"
    if asset.get("final_job_status") == "rendered" and asset.get("approval_status") == "approved":
        return "needs_review"
    if asset.get("final_render_exists"):
        return "needs_review"
    return "final_render_pending"


def build_editing_approval_queue(config: AppConfig) -> dict[str, Any]:
    manifest = build_editing_manifest(config)
    safety = _load(_analytics(config, "editing_safety_report.json"), None)
    if not safety:
        safety = verify_editing_safety(config)
    before_after = _load(_analytics(config, "before_after_compare.json"), {"records": []})
    receipts = _receipts(config)
    rejections = _rejections(config)
    assets = manifest["preview_manifest"].get("assets", [])
    items: list[dict[str, Any]] = []
    for asset in assets:
        receipt = matching_receipt(asset, "edited_social_export", receipts=receipts) or matching_receipt(asset, "final_render", receipts=receipts)
        item = {
            "approval_id": _approval_id(asset),
            "asset_id": asset.get("asset_id"),
            "plan_id": asset.get("plan_id"),
            "clip_id": asset.get("clip_id"),
            "platform": asset.get("platform"),
            "original_path": asset.get("source_path"),
            "preview_path": asset.get("preview_path"),
            "final_render_path": asset.get("final_render_path"),
            "thumbnail_path": asset.get("thumbnail_path"),
            "status": _queue_status(asset, receipts, rejections),
            "original_media_protected": asset.get("original_media_protected") is True,
            "source_overwrite_allowed": False,
            "paths_contained": asset.get("paths_contained") is True,
            "safety_status": safety.get("status", "unknown"),
            "approval_required": True,
            "approval_receipt_id": receipt.get("receipt_id") if receipt else None,
            "created_at": asset.get("created_at") or utc_now(),
            "updated_at": utc_now(),
            "notes": "Review edited preview/final render before approving export.",
        }
        items.append(item)
    payload = {
        "status": "pass",
        "updated_at": utc_now(),
        "items": items,
        "before_after_records": before_after.get("records", []) if isinstance(before_after.get("records"), list) else [],
        "original_media_protected": all(item["original_media_protected"] and not item["source_overwrite_allowed"] for item in items) if items else True,
        "source_overwrite_allowed": False,
    }
    receipts_payload = {"status": "pass", "updated_at": utc_now(), "receipts": receipts}
    rejections_payload = {"status": "pass", "updated_at": utc_now(), "rejections": rejections}
    client = {
        "status": "pass",
        "updated_at": payload["updated_at"],
        "summary": {
            "needs_review": len([item for item in items if item["status"] == "needs_review"]),
            "approved": len([item for item in items if item["status"] == "approved"]),
            "rejected": len([item for item in items if item["status"] == "rejected"]),
            "needs_revision": len([item for item in items if item["status"] == "needs_revision"]),
            "export_ready": len([item for item in items if item["status"] == "export_ready"]),
            "final_render_pending": len([item for item in items if item["status"] == "final_render_pending"]),
            "originals_protected": payload["original_media_protected"],
        },
        "items": items[:50],
    }
    save_json_file(_analytics(config, "editing_approval_queue.json"), payload)
    save_json_file(_analytics(config, "editing_approval_receipts.json"), receipts_payload)
    save_json_file(_analytics(config, "editing_rejection_log.json"), rejections_payload)
    save_json_file(_analytics(config, "client_editing_approval_state.json"), client)
    return {"queue": payload, "receipts": receipts_payload, "rejections": rejections_payload, "client_state": client}


def _match_asset(config: AppConfig, *, asset_id: str | None = None, plan_id: str | None = None, clip_id: str | None = None, platform: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    manifest = build_editing_manifest(config)
    assets = manifest["preview_manifest"].get("assets", [])
    matches = []
    for asset in assets:
        if asset_id and str(asset.get("asset_id")) != str(asset_id):
            continue
        if plan_id and str(asset.get("plan_id")) != str(plan_id):
            continue
        if clip_id and str(asset.get("clip_id")) != str(clip_id):
            continue
        if platform and str(asset.get("platform")) != str(platform):
            continue
        matches.append(asset)
    return (matches[0] if len(matches) == 1 else None, matches)


def approve_edited_asset(
    config: AppConfig,
    *,
    asset_id: str | None = None,
    plan_id: str | None = None,
    clip_id: str | None = None,
    platform: str | None = None,
    scope: str = "preview_only",
    notes: str = "",
    expires_at: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if scope not in APPROVAL_SCOPES:
        result = {"status": "fail", "reason": "invalid_scope", "receipt_created": False}
        save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
        return result
    if dry_run and not any([asset_id, plan_id, clip_id, platform]):
        queue = build_editing_approval_queue(config)
        result = {
            "status": "pass",
            "dry_run": True,
            "receipt_created": False,
            "message": "Dry-run only. Provide an exact asset, plan, clip, or platform match with --write to record approval.",
            "queue_status": queue["client_state"]["summary"],
        }
        save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
        return result
    asset, matches = _match_asset(config, asset_id=asset_id, plan_id=plan_id, clip_id=clip_id, platform=platform)
    if not asset:
        result = {"status": "fail", "reason": "asset_match_required", "match_count": len(matches), "receipt_created": False}
        save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
        return result
    safety_failures = []
    if asset.get("original_media_protected") is not True:
        safety_failures.append("original_media_not_protected")
    if asset.get("source_overwrite_allowed") is True:
        safety_failures.append("source_overwrite_allowed")
    if asset.get("paths_contained") is not True:
        safety_failures.append("paths_not_contained")
    if scope in {"final_render", "edited_social_export"}:
        if asset.get("final_render_path_contained") is not True:
            safety_failures.append("final_render_not_contained")
        if asset.get("source_equals_final_render") is True:
            safety_failures.append("source_equals_final_render")
        if asset.get("final_job_status") != "rendered" or asset.get("final_render_exists") is not True:
            safety_failures.append("final_render_required")
    if scope == "edited_social_export" and asset.get("approval_status") != "approved":
        safety_failures.append("final_render_approval_required")
    if safety_failures:
        result = {"status": "blocked", "reason": "safety_gates_failed", "failures": safety_failures, "asset_id": asset.get("asset_id"), "receipt_created": False}
        save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
        return result
    approved_at = utc_now()
    receipt = {
        "receipt_id": _receipt_id(str(asset.get("asset_id")), scope, approved_at),
        "approval_id": _approval_id(asset),
        "asset_id": asset.get("asset_id"),
        "plan_id": asset.get("plan_id"),
        "clip_id": asset.get("clip_id"),
        "platform": asset.get("platform"),
        "approved_by": "local_operator",
        "approved_at": approved_at,
        "approval_scope": scope,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "output_path": asset.get("final_render_path") if scope != "preview_only" else asset.get("preview_path"),
        "safety_report_reference": relative_path(_analytics(config, "editing_safety_report.json"), config.root),
        "reversible": scope in {"preview_only", "edited_social_export"},
        "expires_at": expires_at,
        "expired": False,
        "valid_for_scope": True,
        "notes": notes,
        "status": "approved",
    }
    if dry_run:
        result = {"status": "pass", "dry_run": True, "receipt_created": False, "receipt": receipt}
        save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
        build_editing_approval_queue(config)
        return result
    receipts = _receipts(config)
    receipts.append(receipt)
    save_json_file(_analytics(config, "editing_approval_receipts.json"), {"status": "pass", "updated_at": utc_now(), "receipts": receipts})
    queue = build_editing_approval_queue(config)
    result = {"status": "pass", "dry_run": False, "receipt_created": True, "receipt": receipt, "queue_status": queue["client_state"]["summary"]}
    save_json_file(_analytics(config, "editing_approval_action_status.json"), result)
    return result


def reject_edited_asset(config: AppConfig, *, asset_id: str | None = None, reason: str = "rejected", notes: str = "", needs_revision: bool = False, dry_run: bool = True) -> dict[str, Any]:
    if dry_run and not asset_id:
        queue = build_editing_approval_queue(config)
        result = {
            "status": "pass",
            "dry_run": True,
            "rejection_recorded": False,
            "message": "Dry-run only. Provide --asset-id with --write to record a rejection.",
            "queue_status": queue["client_state"]["summary"],
        }
        save_json_file(_analytics(config, "editing_rejection_action_status.json"), result)
        return result
    asset, matches = _match_asset(config, asset_id=asset_id)
    if not asset:
        result = {"status": "fail", "reason": "asset_match_required", "match_count": len(matches), "rejection_recorded": False}
        save_json_file(_analytics(config, "editing_rejection_action_status.json"), result)
        return result
    rejection = {
        "rejection_id": "edit_reject_" + hashlib.sha1(f"{asset.get('asset_id')}|{utc_now()}".encode("utf-8")).hexdigest()[:12],
        "asset_id": asset.get("asset_id"),
        "plan_id": asset.get("plan_id"),
        "clip_id": asset.get("clip_id"),
        "platform": asset.get("platform"),
        "status": "needs_revision" if needs_revision else "rejected",
        "reason": reason,
        "notes": notes,
        "media_deleted": False,
        "original_media_protected": True,
        "created_at": utc_now(),
    }
    if dry_run:
        result = {"status": "pass", "dry_run": True, "rejection_recorded": False, "rejection": rejection}
        save_json_file(_analytics(config, "editing_rejection_action_status.json"), result)
        build_editing_approval_queue(config)
        return result
    rejections = _rejections(config)
    rejections.append(rejection)
    save_json_file(_analytics(config, "editing_rejection_log.json"), {"status": "pass", "updated_at": utc_now(), "rejections": rejections})
    queue = build_editing_approval_queue(config)
    result = {"status": "pass", "dry_run": False, "rejection_recorded": True, "rejection": rejection, "queue_status": queue["client_state"]["summary"]}
    save_json_file(_analytics(config, "editing_rejection_action_status.json"), result)
    return result
