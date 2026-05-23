from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .editing_approval import build_editing_approval_queue
from .editing_manifest import build_before_after_compare, build_editing_manifest
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


DELIVERY_ROOT = Path("out") / "client_delivery" / "edited_assets"
DELIVERY_DOC_ROOT = Path("out") / "post_editor" / "delivery"
EDITOR_ROOT = Path("out") / "post_editor"
EDITED_SOCIAL_ROOT = Path("out") / "social_exports_edited"


def _analytics(config: AppConfig, name: str) -> Path:
    return config.analytics_dir / name


def _load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_json_file(path, default or {})


def _resolve(config: AppConfig, value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(str(value)).expanduser()
    path = raw if raw.is_absolute() else config.root / raw
    try:
        return path.resolve()
    except OSError:
        return path


def _inside(path: Path | None, folder: Path) -> bool:
    if not path:
        return False
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (OSError, ValueError):
        return False


def _require_inside(path: Path, folder: Path, message: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(folder.resolve())
    except (OSError, ValueError) as error:
        raise ValueError(message) from error
    return resolved


def _delivery_id(asset: dict[str, Any]) -> str:
    basis = "|".join([str(asset.get("asset_id") or ""), str(asset.get("plan_id") or ""), str(asset.get("platform") or "")])
    return "delivery_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _safe_name(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip()
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw).strip("._-")
    if not clean or clean in {".", ".."}:
        clean = fallback
    return clean[:96]


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
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _unique_folder(base: Path, root: Path) -> Path:
    candidate = _require_inside(base, root, "Delivery package must stay inside out/client_delivery/edited_assets.")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = _require_inside(base.with_name(f"{base.name}_{counter:02d}"), root, "Delivery package must stay inside out/client_delivery/edited_assets.")
    return candidate


def _receipt_for(asset: dict[str, Any], receipts: list[dict[str, Any]], scope: str = "edited_social_export") -> dict[str, Any] | None:
    for receipt in reversed(receipts):
        if receipt.get("asset_id") != asset.get("asset_id"):
            continue
        if receipt.get("plan_id") != asset.get("plan_id"):
            continue
        if str(receipt.get("platform")) != str(asset.get("platform")):
            continue
        if receipt.get("approval_scope") != scope:
            continue
        if receipt.get("original_media_protected") is not True or receipt.get("source_overwrite_allowed") is True:
            continue
        if receipt.get("status") not in {None, "approved", "pass"}:
            continue
        if _receipt_expired(receipt):
            continue
        return receipt
    return None


def _valid_delivery_receipt(item: dict[str, Any], receipts_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    receipt_id = item.get("receipt_id")
    if not receipt_id:
        return None
    receipt = receipts_by_id.get(str(receipt_id))
    if not receipt:
        return None
    if receipt.get("asset_id") != item.get("asset_id"):
        return None
    if receipt.get("plan_id") != item.get("plan_id"):
        return None
    if item.get("clip_id"):
        if not receipt.get("clip_id"):
            return None
        if str(receipt.get("clip_id")) != str(item.get("clip_id")):
            return None
    if str(receipt.get("platform")) != str(item.get("platform")):
        return None
    if receipt.get("approval_scope") != "edited_social_export":
        return None
    if receipt.get("original_media_protected") is not True:
        return None
    if receipt.get("source_overwrite_allowed") is True:
        return None
    if receipt.get("status") not in {None, "approved", "pass"}:
        return None
    if _receipt_expired(receipt):
        return None
    return receipt


def _current_item_statuses(config: AppConfig) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for filename in ("editing_approval_queue.json", "client_editing_approval_state.json", "editing_delivery_room.json", "editing_delivery_manifest.json"):
        payload = _load(_analytics(config, filename), {"items": []})
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = item.get("status") or item.get("delivery_status")
            if not status:
                continue
            for key in (item.get("asset_id"), item.get("plan_id"), item.get("clip_id")):
                if key:
                    statuses[str(key)] = str(status)
            composite = "|".join(str(item.get(field) or "") for field in ("asset_id", "plan_id", "clip_id", "platform"))
            if composite.strip("|"):
                statuses[composite] = str(status)
    return statuses


def _latest_rejection_status(item: dict[str, Any], rejections: list[dict[str, Any]], current_statuses: dict[str, str]) -> str | None:
    item_keys = {str(value) for value in (item.get("asset_id"), item.get("plan_id"), item.get("clip_id")) if value}
    for rejection in reversed(rejections):
        if rejection.get("status") not in {"rejected", "needs_revision"}:
            continue
        rejection_keys = {str(value) for value in (rejection.get("asset_id"), rejection.get("plan_id"), rejection.get("clip_id")) if value}
        if item_keys & rejection_keys:
            return str(rejection.get("status"))
    composite = "|".join(str(item.get(field) or "") for field in ("asset_id", "plan_id", "clip_id", "platform"))
    for key in (*item_keys, composite):
        status = current_statuses.get(key)
        if status in {"rejected", "needs_revision"}:
            return status
    return None


def _rejection_status(asset: dict[str, Any], rejections: list[dict[str, Any]]) -> str:
    for rejection in reversed(rejections):
        if rejection.get("asset_id") == asset.get("asset_id") and rejection.get("status") in {"rejected", "needs_revision"}:
            return str(rejection.get("status"))
    return "none"


def _social_pack_for(config: AppConfig, asset: dict[str, Any]) -> str | None:
    root = config.root / EDITED_SOCIAL_ROOT
    if not root.exists():
        return None
    clip = str(asset.get("clip_id") or "")
    platform = str(asset.get("platform") or "")
    for folder in sorted(path for path in root.rglob("*") if path.is_dir()):
        rel = relative_path(folder, config.root)
        if clip and clip not in rel:
            continue
        if platform and platform not in rel:
            continue
        return rel
    return None


def build_editing_delivery_room(config: AppConfig) -> dict[str, Any]:
    manifests = build_editing_manifest(config)
    approval = build_editing_approval_queue(config)
    before_after = build_before_after_compare(config)
    receipts = approval["receipts"].get("receipts", [])
    rejections = approval["rejections"].get("rejections", [])
    compare_by_clip = {str(item.get("clip_id")): item for item in before_after.get("records", [])}
    items: list[dict[str, Any]] = []
    for asset in manifests["preview_manifest"].get("assets", []):
        receipt = _receipt_for(asset, receipts)
        rejection_status = _rejection_status(asset, rejections)
        approval_item = next((item for item in approval["queue"].get("items", []) if item.get("asset_id") == asset.get("asset_id")), {})
        approval_status = "approved" if receipt else asset.get("approval_status", "required")
        if rejection_status in {"rejected", "needs_revision"}:
            delivery_status = rejection_status
        elif receipt and asset.get("status") == "export_ready":
            delivery_status = "approved_for_delivery"
        elif asset.get("preview_exists") or asset.get("final_render_exists"):
            delivery_status = "ready_for_review"
        else:
            delivery_status = "not_ready"
        item = {
            "delivery_id": _delivery_id(asset),
            "asset_id": asset.get("asset_id"),
            "approval_id": approval_item.get("approval_id"),
            "receipt_id": receipt.get("receipt_id") if receipt else None,
            "plan_id": asset.get("plan_id"),
            "clip_id": asset.get("clip_id"),
            "platform": asset.get("platform"),
            "title": asset.get("clip_id") or asset.get("asset_id"),
            "preview_path": asset.get("preview_path"),
            "final_render_path": asset.get("final_render_path"),
            "thumbnail_path": asset.get("thumbnail_path"),
            "edited_social_pack_path": _social_pack_for(config, asset),
            "before_after_status": compare_by_clip.get(str(asset.get("clip_id")), {}).get("compare_status", "waiting_for_preview"),
            "approval_status": approval_status,
            "rejection_status": rejection_status,
            "delivery_status": delivery_status,
            "original_media_protected": asset.get("original_media_protected") is True,
            "source_overwrite_allowed": False,
            "paths_contained": asset.get("paths_contained") is True,
            "notes": "Only approved edited assets are packaged. Original source media is excluded by default.",
            "created_at": asset.get("created_at") or utc_now(),
            "updated_at": utc_now(),
        }
        items.append(item)
    room = {
        "status": "pass",
        "updated_at": utc_now(),
        "items": items,
        "original_media_protected": all(item["original_media_protected"] and not item["source_overwrite_allowed"] for item in items) if items else True,
        "source_media_included_by_default": False,
    }
    manifest = {
        "status": "pass",
        "updated_at": room["updated_at"],
        "items": [item for item in items if item["delivery_status"] in {"approved_for_delivery", "packaged", "delivered"}],
        "manual_upload_fallback": True,
        "original_media_protected": room["original_media_protected"],
        "source_media_included_by_default": False,
    }
    checklist = {
        "status": "pass",
        "updated_at": room["updated_at"],
        "checks": [
            {"label": "Only approved edited assets are packaged", "pass": True},
            {"label": "Original media is excluded by default", "pass": True},
            {"label": "Source overwrite is blocked", "pass": True},
            {"label": "Delivery package writes under out/client_delivery/edited_assets", "pass": True},
        ],
    }
    client = {
        "status": "pass",
        "updated_at": room["updated_at"],
        "summary": {
            "ready_for_review": len([item for item in items if item["delivery_status"] == "ready_for_review"]),
            "approved_for_delivery": len([item for item in items if item["delivery_status"] == "approved_for_delivery"]),
            "needs_revision": len([item for item in items if item["delivery_status"] == "needs_revision"]),
            "packaged": len([item for item in items if item["delivery_status"] == "packaged"]),
            "delivered": len([item for item in items if item["delivery_status"] == "delivered"]),
            "originals_protected": room["original_media_protected"],
        },
        "items": items[:50],
    }
    save_json_file(_analytics(config, "editing_delivery_room.json"), room)
    save_json_file(_analytics(config, "editing_delivery_manifest.json"), manifest)
    save_json_file(_analytics(config, "client_editing_delivery_state.json"), client)
    save_json_file(_analytics(config, "editing_delivery_checklist.json"), checklist)
    write_delivery_markdown(config, room, manifest, checklist)
    return {"room": room, "manifest": manifest, "client_state": client, "checklist": checklist}


def write_delivery_markdown(config: AppConfig, room: dict[str, Any], manifest: dict[str, Any], checklist: dict[str, Any]) -> dict[str, str]:
    out = config.root / DELIVERY_DOC_ROOT
    out.mkdir(parents=True, exist_ok=True)
    gallery = out / "client_review_gallery.md"
    delivery_manifest = out / "editing_delivery_manifest.md"
    delivery_checklist = out / "delivery_checklist.md"
    approved_items = [
        item for item in manifest.get("items", [])
        if item.get("delivery_status") in {"approved_for_delivery", "packaged", "delivered"}
        and item.get("receipt_id")
        and item.get("original_media_protected") is True
        and item.get("source_overwrite_allowed") is False
        and item.get("paths_contained") is True
    ]
    gallery_lines = [
        "# Edited Asset Review Gallery",
        "",
        "Only approved edited assets are packaged. Original media is protected and not included by default.",
        "",
    ]
    if approved_items:
        gallery_lines.extend(
            f"- {item.get('title')} ({item.get('platform')}): {item.get('delivery_status')} - final: {item.get('final_render_path') or 'pending'}"
            for item in approved_items[:100]
        )
    else:
        gallery_lines.append("No approved edited assets are ready for delivery yet.")
    gallery_lines.append("")
    gallery.write_text("\n".join([
        *gallery_lines,
    ]), encoding="utf-8")
    delivery_manifest.write_text("\n".join([
        "# Edited Delivery Manifest",
        "",
        *[f"- {item.get('title')} receipt={item.get('receipt_id') or 'required'} pack={item.get('edited_social_pack_path') or 'pending'}" for item in manifest.get("items", [])[:100]],
        "",
    ]), encoding="utf-8")
    delivery_checklist.write_text("\n".join([
        "# Delivery Checklist",
        "",
        *[f"- [{'x' if item.get('pass') else ' '}] {item.get('label')}" for item in checklist.get("checks", [])],
        "",
    ]), encoding="utf-8")
    return {
        "client_review_gallery": relative_path(gallery, config.root),
        "editing_delivery_manifest": relative_path(delivery_manifest, config.root),
        "delivery_checklist": relative_path(delivery_checklist, config.root),
    }


def package_edited_assets(
    config: AppConfig,
    *,
    approve: bool = False,
    dry_run: bool = True,
    include_previews: bool = False,
    include_final_renders: bool = True,
    include_edited_social_packs: bool = True,
) -> dict[str, Any]:
    delivery = build_editing_delivery_room(config)
    candidates = [item for item in delivery["room"]["items"] if item.get("delivery_status") == "approved_for_delivery"]
    package_root = (config.root / DELIVERY_ROOT).resolve()
    planned_name = "edited_assets_" + utc_now().replace(":", "").replace("+", "Z")
    package_dir = _unique_folder(package_root / planned_name, package_root)
    copied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if not dry_run and approve:
        package_dir.mkdir(parents=True, exist_ok=False)
    for item in candidates:
        final_path = _resolve(config, item.get("final_render_path"))
        if include_final_renders:
            if not final_path or not final_path.exists() or not _inside(final_path, config.root / EDITOR_ROOT / "renders"):
                skipped.append({"delivery_id": item.get("delivery_id"), "reason": "approved_final_render_missing_or_uncontained"})
                continue
            if not dry_run and approve:
                target = _require_inside(package_dir / "final_renders" / final_path.name, package_root, "Delivery target must stay inside out/client_delivery/edited_assets.")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(final_path, target)
                copied.append({"type": "final_render", "path": relative_path(target, config.root)})
        thumb_path = _resolve(config, item.get("thumbnail_path"))
        if thumb_path and thumb_path.exists() and _inside(thumb_path, config.root / EDITOR_ROOT / "thumbnails") and not dry_run and approve:
            target = _require_inside(package_dir / "thumbnails" / thumb_path.name, package_root, "Delivery thumbnail target must stay inside out/client_delivery/edited_assets.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(thumb_path, target)
            copied.append({"type": "thumbnail", "path": relative_path(target, config.root)})
        if include_previews:
            preview_path = _resolve(config, item.get("preview_path"))
            if preview_path and preview_path.exists() and _inside(preview_path, config.root / EDITOR_ROOT / "previews") and not dry_run and approve:
                target = _require_inside(package_dir / "previews" / preview_path.name, package_root, "Delivery preview target must stay inside out/client_delivery/edited_assets.")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(preview_path, target)
                copied.append({"type": "preview", "path": relative_path(target, config.root)})
        if include_edited_social_packs and item.get("edited_social_pack_path") and not dry_run and approve:
            pack_path = _resolve(config, item.get("edited_social_pack_path"))
            if pack_path and pack_path.exists() and _inside(pack_path, config.root / EDITED_SOCIAL_ROOT):
                target_dir = _require_inside(package_dir / "edited_social_packs" / pack_path.name, package_root, "Delivery social pack target must stay inside out/client_delivery/edited_assets.")
                shutil.copytree(pack_path, target_dir)
                copied.append({"type": "edited_social_pack", "path": relative_path(target_dir, config.root)})
    result = {
        "status": "pass",
        "updated_at": utc_now(),
        "dry_run": dry_run,
        "approved": approve,
        "candidate_count": len(candidates),
        "packaged_count": len(copied) if approve and not dry_run else 0,
        "planned_package_path": relative_path(package_dir, config.root),
        "copied": copied,
        "skipped": skipped,
        "original_media_included": False,
        "source_overwrite_allowed": False,
    }
    if not dry_run and approve:
        save_json_file(package_dir / "delivery_manifest.json", delivery["manifest"])
        save_json_file(package_dir / "edit_manifest.json", delivery["room"])
        save_json_file(package_dir / "original_protection_proof.json", _protection_proof())
        (package_dir / "README_CLIENT_REVIEW.md").write_text("Use this folder to review or deliver finished edited posts. Original source media is excluded by default.\n", encoding="utf-8")
        (package_dir / "delivery_checklist.md").write_text("# Delivery Checklist\n\n- [x] Approved edited assets only\n- [x] Original media excluded by default\n- [x] Source overwrite blocked\n", encoding="utf-8")
    save_json_file(_analytics(config, "edited_delivery_package_status.json"), result)
    return result


def verify_edited_delivery_package(config: AppConfig) -> dict[str, Any]:
    package_status = _load(_analytics(config, "edited_delivery_package_status.json"), {"dry_run": True})
    package_root = (config.root / DELIVERY_ROOT).resolve()
    failures: list[dict[str, Any]] = []
    package_path = _resolve(config, package_status.get("planned_package_path"))
    if package_status.get("dry_run") is True:
        status = "pass"
    else:
        if not package_path or not package_path.exists():
            failures.append({"reason": "package_missing"})
        elif not _inside(package_path, package_root):
            failures.append({"reason": "package_outside_delivery_root"})
        else:
            forbidden_names = {
                "content_inbox",
                "clips",
                "config",
                ".social_token_vault.local",
                "social_connectors.json",
                "runtime_state.db",
                "events.jsonl",
            }
            for path in package_path.rglob("*"):
                if not _inside(path, package_root):
                    failures.append({"path": relative_path(path, config.root), "reason": "package_child_outside_delivery_root"})
                if any(part in forbidden_names for part in path.parts):
                    failures.append({"path": relative_path(path, config.root), "reason": "forbidden_private_path"})
                if path.is_file() and any(term in path.name.lower() for term in ("token", "secret", "credential", "password")):
                    failures.append({"path": relative_path(path, config.root), "reason": "possible_secret_file"})
            for name in ("delivery_manifest.json", "original_protection_proof.json", "README_CLIENT_REVIEW.md", "delivery_checklist.md"):
                if not (package_path / name).exists():
                    failures.append({"path": relative_path(package_path / name, config.root), "reason": "required_delivery_file_missing"})
            manifest_path = package_path / "delivery_manifest.json"
            manifest = _load(manifest_path, {"items": []}) if manifest_path.exists() else {"items": []}
            manifest_items = manifest.get("items", []) if isinstance(manifest.get("items"), list) else []
            receipt_payload = _load(_analytics(config, "editing_approval_receipts.json"), {"receipts": []})
            receipt_list = receipt_payload.get("receipts", []) if isinstance(receipt_payload.get("receipts"), list) else []
            receipts_by_id = {str(receipt.get("receipt_id")): receipt for receipt in receipt_list if isinstance(receipt, dict) and receipt.get("receipt_id")}
            rejection_payload = _load(_analytics(config, "editing_rejection_log.json"), {"rejections": []})
            rejections = rejection_payload.get("rejections", []) if isinstance(rejection_payload.get("rejections"), list) else []
            current_statuses = _current_item_statuses(config)
            approved_names: set[str] = set()
            approved_items_by_name: dict[str, dict[str, Any]] = {}
            for item in manifest_items:
                if not isinstance(item, dict):
                    continue
                final_render = _resolve(config, item.get("final_render_path"))
                receipt = _valid_delivery_receipt(item, receipts_by_id)
                rejection_status = _latest_rejection_status(item, rejections, current_statuses)
                current_delivery_status = current_statuses.get(str(item.get("asset_id") or "")) or current_statuses.get(str(item.get("plan_id") or ""))
                valid_item = (
                    item.get("delivery_status") in {"approved_for_delivery", "packaged", "delivered"}
                    and item.get("receipt_id")
                    and receipt is not None
                    and rejection_status is None
                    and (current_delivery_status in {None, "approved_for_delivery", "packaged", "delivered", "export_ready", "approved"})
                    and item.get("original_media_protected") is True
                    and item.get("source_overwrite_allowed") is False
                    and item.get("paths_contained") is True
                    and final_render is not None
                    and _inside(final_render, config.root / EDITOR_ROOT / "renders")
                )
                if not valid_item:
                    reason = "invalid_or_unapproved_delivery_manifest_item"
                    if rejection_status == "rejected":
                        reason = "rejected_asset_in_package"
                    elif rejection_status == "needs_revision":
                        reason = "needs_revision_asset_in_package"
                    elif current_delivery_status not in {None, "approved_for_delivery", "packaged", "delivered", "export_ready", "approved"}:
                        reason = "package_manifest_not_current"
                    elif item.get("clip_id") and receipt is None:
                        reason = "receipt_clip_id_mismatch"
                    failures.append({"asset_id": item.get("asset_id"), "reason": reason})
                    continue
                approved_names.add(final_render.name)
                approved_items_by_name[final_render.name] = item
            final_root = package_path / "final_renders"
            if final_root.exists():
                for path in final_root.rglob("*"):
                    if not path.is_file():
                        continue
                    if not _inside(path, package_root):
                        failures.append({"path": relative_path(path, config.root), "reason": "final_render_outside_delivery_root"})
                        continue
                    if path.name not in approved_names:
                        failures.append({"path": relative_path(path, config.root), "reason": "unapproved_or_unmanifested_final_render"})
                    elif not _valid_delivery_receipt(approved_items_by_name[path.name], receipts_by_id):
                        failures.append({"path": relative_path(path, config.root), "reason": "invalid_or_missing_delivery_receipt"})
            elif approved_names:
                failures.append({"path": relative_path(final_root, config.root), "reason": "approved_final_render_folder_missing"})
        status = "pass" if not failures else "fail"
    report = {
        "status": status,
        "updated_at": utc_now(),
        "dry_run": package_status.get("dry_run", True),
        "package_path": package_status.get("planned_package_path"),
        "failures": failures,
        "original_media_included": False,
        "source_overwrite_allowed": False,
    }
    save_json_file(_analytics(config, "edited_delivery_package_verification.json"), report)
    return report


def record_editing_delivery_note(config: AppConfig, *, asset_id: str | None = None, status: str = "approved", note: str = "", dry_run: bool = True) -> dict[str, Any]:
    if status not in {"approved", "rejected", "needs_revision", "delivered"}:
        result = {"status": "fail", "reason": "invalid_delivery_note_status", "recorded": False}
        save_json_file(_analytics(config, "editing_delivery_note_status.json"), result)
        return result
    existing = _load(_analytics(config, "editing_delivery_notes.json"), {"notes": []})
    notes = existing.get("notes", []) if isinstance(existing.get("notes"), list) else []
    record = {
        "note_id": "delivery_note_" + hashlib.sha1(f"{asset_id}|{status}|{utc_now()}".encode("utf-8")).hexdigest()[:12],
        "asset_id": asset_id,
        "status": status,
        "note": note,
        "media_deleted": False,
        "original_media_protected": True,
        "created_at": utc_now(),
    }
    if not dry_run:
        notes.append(record)
        save_json_file(_analytics(config, "editing_delivery_notes.json"), {"status": "pass", "updated_at": utc_now(), "notes": notes})
    result = {"status": "pass", "dry_run": dry_run, "recorded": not dry_run, "note": record}
    save_json_file(_analytics(config, "editing_delivery_note_status.json"), result)
    return result


def _protection_proof() -> dict[str, Any]:
    return {
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "source_media_included_by_default": False,
        "proof": "Delivery packages include approved edited outputs only and exclude original private source media by default.",
        "created_at": utc_now(),
    }
