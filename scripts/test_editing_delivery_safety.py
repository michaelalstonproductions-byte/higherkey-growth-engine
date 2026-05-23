#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.editing_approval import approve_edited_asset, reject_edited_asset
from growth_engine.editing_delivery import build_editing_delivery_room, package_edited_assets, verify_edited_delivery_package
from growth_engine.editing_manifest import build_editing_manifest
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file


def _plan(plan_id: str, clip_id: str, render_path: str, source_path: str = "content_inbox/original.mp4") -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "clip_id": clip_id,
        "platform": "tiktok",
        "source_path": source_path,
        "preview_path": f"out/post_editor/previews/{plan_id}.mp4",
        "render_path": render_path,
        "thumbnail_path": f"out/post_editor/thumbnails/{plan_id}.jpg",
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "created_at": utc_now(),
    }


def _job(plan_id: str, approved: bool = True) -> dict[str, object]:
    return {"job_id": f"job_{plan_id}", "plan_id": plan_id, "type": "final_render", "status": "rendered", "approved": approved, "created_at": utc_now()}


def _write_fixture(root: Path) -> None:
    analytics = root / "analytics"
    for path in (
        analytics,
        root / "content_inbox",
        root / "clips",
        root / "out/post_editor/renders",
        root / "out/post_editor/previews",
        root / "out/post_editor/thumbnails",
        root / "out/post_editor/renders_evil",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (root / "content_inbox/original.mp4").write_bytes(b"private-source")
    (root / "clips/raw_clip.mp4").write_bytes(b"raw-clip")
    (root / "out/post_editor/renders/approved.mp4").write_bytes(b"approved-final")
    (root / "out/post_editor/renders/rejected.mp4").write_bytes(b"rejected-final")
    (root / "out/post_editor/renders/revision.mp4").write_bytes(b"revision-final")
    (root / "out/post_editor/renders/unapproved.mp4").write_bytes(b"unapproved-final")
    (root / "out/post_editor/renders_evil/bad.mp4").write_bytes(b"bad-final")
    (root / "out/post_editor/thumbnails/approved.jpg").write_bytes(b"thumb")
    plans = [
        _plan("approved_plan", "approved_clip", "out/post_editor/renders/approved.mp4"),
        _plan("rejected_plan", "rejected_clip", "out/post_editor/renders/rejected.mp4"),
        _plan("revision_plan", "revision_clip", "out/post_editor/renders/revision.mp4"),
        _plan("unapproved_plan", "unapproved_clip", "out/post_editor/renders/unapproved.mp4"),
        _plan("outside_plan", "outside_clip", "out/post_editor/renders_evil/bad.mp4"),
    ]
    jobs = [_job("approved_plan", True), _job("rejected_plan", True), _job("revision_plan", True), _job("unapproved_plan", False), _job("outside_plan", True)]
    save_json_file(analytics / "edit_plans.json", {"plans": plans})
    save_json_file(analytics / "edit_jobs.json", {"jobs": jobs})
    save_json_file(analytics / "post_editing_recommendations.json", {"recommendations": []})
    save_json_file(analytics / "before_after_compare.json", {"status": "pass", "records": [], "media_modified": False})


def main() -> int:
    scratch = ROOT / "out" / "editing_delivery_safety_fixture" / "project"
    if scratch.exists():
        shutil.rmtree(scratch)
    _write_fixture(scratch)
    config = load_config(scratch)
    failures: list[str] = []

    manifest = build_editing_manifest(config)
    by_plan = {asset["plan_id"]: asset for asset in manifest["preview_manifest"]["assets"]}
    approve_edited_asset(config, plan_id="approved_plan", platform="tiktok", scope="edited_social_export", dry_run=False)
    approve_edited_asset(config, plan_id="rejected_plan", platform="tiktok", scope="edited_social_export", dry_run=False)
    approve_edited_asset(config, plan_id="revision_plan", platform="tiktok", scope="edited_social_export", dry_run=False)
    reject_edited_asset(config, asset_id=by_plan["rejected_plan"]["asset_id"], reason="fixture reject", dry_run=False)
    reject_edited_asset(config, asset_id=by_plan["revision_plan"]["asset_id"], reason="fixture revision", needs_revision=True, dry_run=False)

    room = build_editing_delivery_room(config)
    status_by_plan = {item["clip_id"].replace("_clip", "_plan"): item["delivery_status"] for item in room["room"]["items"] if item.get("clip_id")}
    if status_by_plan.get("rejected_plan") not in {"rejected", None}:
        failures.append("rejected asset was delivery-ready")
    if status_by_plan.get("revision_plan") not in {"needs_revision", None}:
        failures.append("needs_revision asset was delivery-ready")
    if status_by_plan.get("unapproved_plan") == "approved_for_delivery":
        failures.append("unapproved asset became approved_for_delivery")
    gallery = scratch / "out/post_editor/delivery/client_review_gallery.md"
    gallery_text = gallery.read_text(encoding="utf-8") if gallery.exists() else ""
    if "approved_clip" not in gallery_text:
        failures.append("approved delivery item missing from client review gallery")
    for blocked_clip in ("rejected_clip", "revision_clip", "unapproved_clip", "outside_clip"):
        if blocked_clip in gallery_text:
            failures.append(f"{blocked_clip} appeared in client review gallery")

    dry = package_edited_assets(config, dry_run=True, approve=False)
    delivery_root = scratch / "out/client_delivery/edited_assets"
    if delivery_root.exists() and any(delivery_root.rglob("*")):
        failures.append("dry-run wrote delivery package files")
    if dry.get("original_media_included") is not False:
        failures.append("dry-run did not report original media excluded")

    approved = package_edited_assets(config, dry_run=False, approve=True)
    verify = verify_edited_delivery_package(config)
    if approved.get("status") != "pass" or verify.get("status") != "pass":
        failures.append("approved delivery package or verification failed")
    package_path = scratch / approved.get("planned_package_path", "")
    if not package_path.resolve().is_relative_to(delivery_root.resolve()):
        failures.append("delivery package escaped approved root")
    copied = list(package_path.rglob("*")) if package_path.exists() else []
    if any("content_inbox" in path.parts or "clips" in path.parts for path in copied):
        failures.append("original source media folder was included")
    if any(path.name in {"social_connectors.json", ".social_token_vault.local"} or "token" in path.name.lower() or "secret" in path.name.lower() for path in copied):
        failures.append("token or secret-like file included")
    for required in ("delivery_manifest.json", "original_protection_proof.json", "README_CLIENT_REVIEW.md", "delivery_checklist.md"):
        if not (package_path / required).exists():
            failures.append(f"missing {required}")
    extra_final = package_path / "final_renders" / "unapproved_extra.mp4"
    extra_final.parent.mkdir(parents=True, exist_ok=True)
    extra_final.write_bytes(b"unapproved-extra")
    extra_verify = verify_edited_delivery_package(config)
    if extra_verify.get("status") != "fail":
        failures.append("delivery verifier accepted extra unapproved final render")
    extra_final.unlink(missing_ok=True)
    secret_file = package_path / "token.txt"
    secret_file.write_text("not-a-real-token", encoding="utf-8")
    secret_verify = verify_edited_delivery_package(config)
    if secret_verify.get("status") != "fail":
        failures.append("delivery verifier accepted token-like file")
    secret_file.unlink(missing_ok=True)
    clean_verify = verify_edited_delivery_package(config)
    if clean_verify.get("status") != "pass":
        failures.append("delivery verifier did not recover after removing malicious files")

    second = package_edited_assets(config, dry_run=False, approve=True)
    if second.get("planned_package_path") == approved.get("planned_package_path"):
        failures.append("second delivery package overwrote previous package")
    save_json_file(config.analytics_dir / "edited_delivery_package_status.json", {
        "status": "pass",
        "dry_run": False,
        "planned_package_path": "out/client_delivery/edited_assets_evil/package",
        "original_media_included": False,
        "source_overwrite_allowed": False,
    })
    escape_verify = verify_edited_delivery_package(config)
    if escape_verify.get("status") != "fail":
        failures.append("delivery package verifier accepted sibling-prefix escape path")
    evil = scratch / "out/client_delivery/edited_assets_evil"
    if evil.exists():
        failures.append("sibling delivery escape folder was created")

    report = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "scratch_root": str(scratch.relative_to(ROOT)),
    }
    save_json_file(ROOT / "analytics" / "editing_delivery_safety_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
