from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


EDITOR_BASE = Path("out") / "post_editor"
EDITED_EXPORT_BASE = Path("out") / "social_exports_edited"


def _analytics(config: AppConfig, name: str) -> Path:
    return config.analytics_dir / name


def _load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_json_file(path, default or {})


def _resolve(config: AppConfig, value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value).expanduser()
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


def _safe_segment(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip()
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.replace("/", "-").replace("\\", "-")).strip("._-")
    if not segment or segment in {".", ".."}:
        raise ValueError("Edited export folder segment is unsafe.")
    return segment[:96]


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


def _safe_rel(config: AppConfig, value: str | None) -> str | None:
    path = _resolve(config, value)
    return relative_path(path, config.root) if path else None


def _job_for(jobs: list[dict[str, Any]], plan_id: str, job_type: str) -> dict[str, Any] | None:
    matches = [job for job in jobs if str(job.get("plan_id")) == str(plan_id) and job.get("type") == job_type]
    return matches[-1] if matches else None


def _approval_receipts(config: AppConfig) -> list[dict[str, Any]]:
    receipts = _load(_analytics(config, "editing_approval_receipts.json"), {"receipts": []}).get("receipts", [])
    return receipts if isinstance(receipts, list) else []


def _rejections(config: AppConfig) -> list[dict[str, Any]]:
    rejections = _load(_analytics(config, "editing_rejection_log.json"), {"rejections": []}).get("rejections", [])
    return rejections if isinstance(rejections, list) else []


def _matching_export_receipt(asset: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    for receipt in reversed(receipts):
        if receipt.get("asset_id") != asset.get("asset_id"):
            continue
        if receipt.get("plan_id") != asset.get("plan_id"):
            continue
        if str(receipt.get("platform")) != str(asset.get("platform")):
            continue
        if receipt.get("approval_scope") != "edited_social_export":
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


def _asset_rejected(asset: dict[str, Any], rejections: list[dict[str, Any]]) -> bool:
    for rejection in reversed(rejections):
        if rejection.get("asset_id") == asset.get("asset_id") and rejection.get("status") in {"rejected", "needs_revision"}:
            return True
    return False


def _asset_id(plan: dict[str, Any]) -> str:
    basis = "|".join([str(plan.get("plan_id") or ""), str(plan.get("clip_id") or ""), str(plan.get("platform") or "")])
    return "edited_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _asset_status(
    preview_job: dict[str, Any] | None,
    final_job: dict[str, Any] | None,
    final_path: Path | None,
    *,
    export_eligible: bool,
) -> str:
    if final_job and final_job.get("status") == "failed":
        return "failed"
    if export_eligible:
        return "export_ready"
    if final_job and final_job.get("status") == "rendered":
        return "final_rendered"
    if final_job and final_job.get("approved") is not True:
        return "final_pending_approval"
    if preview_job and str(preview_job.get("status", "")).startswith(("preview_ready", "rendered")):
        return "preview_ready"
    return "planned"


def build_editing_manifest(config: AppConfig) -> dict[str, Any]:
    plans = _load(_analytics(config, "edit_plans.json"), {"plans": []}).get("plans", [])
    jobs = _load(_analytics(config, "edit_jobs.json"), {"jobs": []}).get("jobs", [])
    recs = _load(_analytics(config, "post_editing_recommendations.json"), {"recommendations": []})
    plans = plans if isinstance(plans, list) else []
    jobs = jobs if isinstance(jobs, list) else []
    receipts = _approval_receipts(config)
    rejections = _rejections(config)
    editor_root = config.root / EDITOR_BASE
    previews_root = editor_root / "previews"
    renders_root = editor_root / "renders"
    thumbnails_root = editor_root / "thumbnails"
    assets: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        plan_id = str(plan.get("plan_id") or "")
        source = _resolve(config, plan.get("source_path"))
        preview = _resolve(config, plan.get("preview_path"))
        final = _resolve(config, plan.get("render_path"))
        thumb = _resolve(config, plan.get("thumbnail_path"))
        preview_job = _job_for(jobs, plan_id, "preview")
        final_job = _job_for(jobs, plan_id, "final_render")
        preview_contained = _inside(preview, previews_root) if preview else True
        final_contained = _inside(final, renders_root) if final else False
        thumbnail_contained = _inside(thumb, thumbnails_root) if thumb else True
        source_equals_final = bool(source and final and source.resolve() == final.resolve())
        paths_contained = preview_contained and final_contained and thumbnail_contained
        receipt_probe = {
            "asset_id": _asset_id(plan),
            "plan_id": plan_id,
            "platform": plan.get("platform") or "tiktok",
        }
        export_receipt = _matching_export_receipt(receipt_probe, receipts)
        rejected_or_revision = _asset_rejected(receipt_probe, rejections)
        export_eligible = bool(
            final_job
            and final_job.get("status") == "rendered"
            and final_job.get("approved") is True
            and final
            and final.exists()
            and paths_contained
            and final_contained
            and plan.get("original_media_protected", True) is True
            and plan.get("source_overwrite_allowed", False) is not True
            and not source_equals_final
            and export_receipt
            and not rejected_or_revision
        )
        status = _asset_status(preview_job, final_job, final, export_eligible=export_eligible)
        asset = {
            "asset_id": _asset_id(plan),
            "plan_id": plan_id,
            "clip_id": plan.get("clip_id"),
            "source_path": _safe_rel(config, plan.get("source_path")),
            "preview_path": _safe_rel(config, plan.get("preview_path")),
            "final_render_path": _safe_rel(config, plan.get("render_path")),
            "thumbnail_path": _safe_rel(config, plan.get("thumbnail_path")),
            "preview_exists": bool(preview and preview.exists()),
            "final_render_exists": bool(final and final.exists()),
            "thumbnail_exists": bool(thumb and thumb.exists()),
            "platform": plan.get("platform") or "tiktok",
            "status": status,
            "original_media_protected": bool(plan.get("original_media_protected", True)),
            "source_exists": bool(source and source.exists()),
            "source_overwrite_allowed": False,
            "approval_required": True,
            "approval_status": "approved" if final_job and final_job.get("approved") is True else "required",
            "edited_export_receipt_id": export_receipt.get("receipt_id") if export_receipt else None,
            "edited_export_approval_required": export_receipt is None,
            "rejected_or_needs_revision": rejected_or_revision,
            "preview_job_status": preview_job.get("status") if preview_job else "not_run",
            "final_job_status": final_job.get("status") if final_job else "not_run",
            "paths_contained": paths_contained,
            "preview_path_contained": preview_contained,
            "final_render_path_contained": final_contained,
            "thumbnail_path_contained": thumbnail_contained,
            "source_equals_final_render": source_equals_final,
            "created_at": plan.get("created_at") or utc_now(),
            "updated_at": utc_now(),
        }
        assets.append(asset)
    preview_manifest = {
        "status": "pass",
        "updated_at": utc_now(),
        "local_only": True,
        "cloud_editing_api_enabled": False,
        "assets": assets,
        "recommendation_count": len(recs.get("recommendations", []) if isinstance(recs.get("recommendations"), list) else []),
        "output_root": relative_path(editor_root, config.root),
    }
    edited_assets = {
        "status": "pass",
        "updated_at": preview_manifest["updated_at"],
        "export_ready_count": len([asset for asset in assets if asset["status"] == "export_ready"]),
        "assets": [asset for asset in assets if asset["status"] in {"final_rendered", "export_ready"}],
        "manual_upload_fallback": True,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
    }
    client = {
        "status": "pass",
        "updated_at": preview_manifest["updated_at"],
        "summary": {
            "plans_ready": len(assets),
            "previews_ready": len([asset for asset in assets if asset["status"] == "preview_ready" or asset["preview_exists"]]),
            "final_renders_waiting_approval": len([asset for asset in assets if asset["status"] == "final_pending_approval"]),
            "edited_packs_ready": edited_assets["export_ready_count"],
            "originals_protected": all(asset["original_media_protected"] and not asset["source_overwrite_allowed"] for asset in assets) if assets else True,
            "failed_jobs": len([asset for asset in assets if asset["status"] == "failed"]),
        },
        "assets": assets[:25],
    }
    save_json_file(_analytics(config, "editing_preview_manifest.json"), preview_manifest)
    save_json_file(_analytics(config, "edited_asset_manifest.json"), edited_assets)
    save_json_file(_analytics(config, "client_editing_manifest.json"), client)
    return {"preview_manifest": preview_manifest, "edited_asset_manifest": edited_assets, "client_manifest": client}


def verify_editing_safety(config: AppConfig) -> dict[str, Any]:
    manifests = build_editing_manifest(config)
    assets = manifests["preview_manifest"]["assets"]
    editor_root = (config.root / EDITOR_BASE).resolve()
    failures: list[dict[str, Any]] = []
    for asset in assets:
        source = _resolve(config, asset.get("source_path"))
        outputs = [
            ("preview_path", _resolve(config, asset.get("preview_path"))),
            ("final_render_path", _resolve(config, asset.get("final_render_path"))),
            ("thumbnail_path", _resolve(config, asset.get("thumbnail_path"))),
        ]
        if source and asset.get("source_exists") and not source.exists():
            failures.append({"asset_id": asset.get("asset_id"), "reason": "source_missing"})
        for key, out_path in outputs:
            if not out_path:
                continue
            if not _inside(out_path, editor_root):
                failures.append({"asset_id": asset.get("asset_id"), "path": key, "reason": "output_outside_post_editor"})
            if source and source.resolve() == out_path.resolve():
                failures.append({"asset_id": asset.get("asset_id"), "path": key, "reason": "source_equals_output"})
        if asset.get("source_overwrite_allowed") is True or asset.get("original_media_protected") is not True:
            failures.append({"asset_id": asset.get("asset_id"), "reason": "protection_flag_failed"})
        if asset.get("paths_contained") is not True:
            failures.append({"asset_id": asset.get("asset_id"), "reason": "output_path_not_contained"})
        if asset.get("final_job_status") == "rendered" and asset.get("final_render_path_contained") is not True:
            failures.append({"asset_id": asset.get("asset_id"), "reason": "final_render_not_in_renders"})
        if asset.get("source_equals_final_render") is True:
            failures.append({"asset_id": asset.get("asset_id"), "reason": "source_equals_final_render"})
        if asset.get("final_job_status") == "rendered" and asset.get("approval_status") != "approved":
            failures.append({"asset_id": asset.get("asset_id"), "reason": "final_render_without_approval"})
        if asset.get("status") == "export_ready" and not asset.get("edited_export_receipt_id"):
            failures.append({"asset_id": asset.get("asset_id"), "reason": "edited_export_receipt_required"})
        if asset.get("status") == "export_ready" and asset.get("rejected_or_needs_revision") is True:
            failures.append({"asset_id": asset.get("asset_id"), "reason": "rejected_asset_export_ready"})
    report = {
        "status": "pass" if not failures else "fail",
        "updated_at": utc_now(),
        "checked_assets": len(assets),
        "failures": failures,
        "original_media_protected": not failures,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "output_root": relative_path(editor_root, config.root),
    }
    save_json_file(_analytics(config, "editing_safety_report.json"), report)
    return report


def build_before_after_compare(config: AppConfig) -> dict[str, Any]:
    manifests = build_editing_manifest(config)
    records = []
    for asset in manifests["preview_manifest"]["assets"]:
        records.append(
            {
                "clip_id": asset.get("clip_id"),
                "original_path": asset.get("source_path"),
                "preview_path": asset.get("preview_path"),
                "final_path": asset.get("final_render_path"),
                "thumbnail_path": asset.get("thumbnail_path"),
                "compare_status": "ready" if asset.get("preview_exists") or asset.get("final_render_exists") else "waiting_for_preview",
                "notes": "Comparison metadata only; media files are not altered.",
            }
        )
    payload = {"status": "pass", "updated_at": utc_now(), "records": records, "media_modified": False}
    save_json_file(_analytics(config, "before_after_compare.json"), payload)
    return payload


def export_edited_social_assets(
    config: AppConfig,
    *,
    approve: bool = False,
    dry_run: bool = True,
    platform: str | None = None,
    clip_id: str | None = None,
) -> dict[str, Any]:
    manifests = build_editing_manifest(config)
    candidates = []
    for asset in manifests["edited_asset_manifest"]["assets"]:
        if asset.get("status") != "export_ready":
            continue
        if platform and str(asset.get("platform")) != str(platform):
            continue
        if clip_id and str(asset.get("clip_id")) != str(clip_id):
            continue
        candidates.append(asset)
    export_root = config.root / EDITED_EXPORT_BASE
    exported = []
    skipped = []
    if not dry_run and not approve:
        status = "approval_required"
    else:
        status = "pass"
    drafts = _load(_analytics(config, "post_composer_drafts.json"), {"drafts": []}).get("drafts", [])
    drafts = drafts if isinstance(drafts, list) else []
    for asset in candidates:
        source = _resolve(config, asset.get("final_render_path"))
        if not source or not source.exists():
            skipped.append({"asset_id": asset.get("asset_id"), "reason": "final_render_missing"})
            continue
        render_root = (config.root / EDITOR_BASE / "renders").resolve()
        export_root_resolved = export_root.resolve()
        if not asset.get("paths_contained") or not asset.get("final_render_path_contained"):
            skipped.append({"asset_id": asset.get("asset_id"), "reason": "final_render_not_contained"})
            continue
        if not asset.get("edited_export_receipt_id"):
            skipped.append({"asset_id": asset.get("asset_id"), "reason": "edited_export_receipt_required"})
            continue
        try:
            source = _require_inside(source, render_root, "Final render must stay inside out/post_editor/renders.")
        except ValueError:
            skipped.append({"asset_id": asset.get("asset_id"), "reason": "final_render_not_contained"})
            continue
        if not dry_run and approve:
            try:
                platform_segment = _safe_segment(asset.get("platform"), "platform")
                clip_segment = _safe_segment(asset.get("clip_id") or asset.get("asset_id"), "asset")
            except ValueError:
                skipped.append({"asset_id": asset.get("asset_id"), "reason": "unsafe_export_segment"})
                continue
            pack_dir = _unique_pack_dir(export_root / platform_segment / clip_segment, export_root_resolved)
            try:
                pack_dir = _require_inside(pack_dir, export_root_resolved, "Edited export pack must stay inside out/social_exports_edited.")
            except ValueError:
                skipped.append({"asset_id": asset.get("asset_id"), "reason": "export_path_not_contained"})
                continue
            pack_dir.mkdir(parents=True, exist_ok=False)
            target = _require_inside(pack_dir / source.name, export_root_resolved, "Edited export target must stay inside out/social_exports_edited.")
            shutil.copy2(source, target)
            draft = _matching_draft(drafts, asset)
            _write_text(pack_dir / "caption.txt", draft.get("generated_caption") or draft.get("user_caption_override") or "")
            _write_text(pack_dir / "hashtags.txt", " ".join(draft.get("hashtags") or []))
            _write_text(pack_dir / "title.txt", draft.get("title") or asset.get("clip_id") or "")
            _write_text(pack_dir / "posting_notes.txt", "Manual upload fallback remains available. Review before posting.")
            save_json_file(pack_dir / "edit_manifest.json", asset)
            save_json_file(pack_dir / "original_protection_proof.json", _protection_proof(asset))
            exported.append({"asset_id": asset["asset_id"], "folder": relative_path(pack_dir, config.root), "media": relative_path(target, config.root)})
        else:
            exported.append({"asset_id": asset["asset_id"], "folder": relative_path(export_root, config.root), "dry_run": True})
    result = {
        "status": status,
        "updated_at": utc_now(),
        "dry_run": dry_run,
        "approved": approve,
        "candidate_count": len(candidates),
        "exported_count": len(exported) if (dry_run or approve) else 0,
        "skipped": skipped,
        "exports": exported if (dry_run or approve) else [],
        "output_root": relative_path(export_root, config.root),
        "original_media_protected": True,
        "unapproved_assets_exported": False,
    }
    save_json_file(_analytics(config, "edited_social_export_status.json"), result)
    return result


def _unique_pack_dir(base: Path, export_root: Path) -> Path:
    candidate = _require_inside(base, export_root, "Edited export pack must stay inside out/social_exports_edited.")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = _require_inside(base.with_name(f"{base.name}_{counter:02d}"), export_root, "Edited export pack must stay inside out/social_exports_edited.")
    return candidate


def _matching_draft(drafts: list[dict[str, Any]], asset: dict[str, Any]) -> dict[str, Any]:
    for draft in drafts:
        if str(draft.get("clip_id")) == str(asset.get("clip_id")) and str(draft.get("platform")) == str(asset.get("platform")):
            return draft
    return {}


def _write_text(path: Path, value: str) -> None:
    path.write_text(str(value or "") + "\n", encoding="utf-8")


def _protection_proof(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": asset.get("asset_id"),
        "plan_id": asset.get("plan_id"),
        "source_path": asset.get("source_path"),
        "final_render_path": asset.get("final_render_path"),
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "proof": "Edited exports copy approved render outputs only and never overwrite source media.",
        "created_at": utc_now(),
    }
