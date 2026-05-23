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
from growth_engine.editing_approval import approve_edited_asset, build_editing_approval_queue, reject_edited_asset
from growth_engine.editing_manifest import build_editing_manifest, export_edited_social_assets
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file


def _plan(plan_id: str, clip_id: str, platform: str, source_path: str, render_path: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "clip_id": clip_id,
        "platform": platform,
        "source_path": source_path,
        "render_path": render_path,
        "preview_path": f"out/post_editor/previews/{plan_id}.mp4",
        "thumbnail_path": f"out/post_editor/thumbnails/{plan_id}.jpg",
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "created_at": utc_now(),
    }


def _job(plan_id: str, approved: bool = True) -> dict[str, object]:
    return {
        "job_id": f"job_{plan_id}",
        "plan_id": plan_id,
        "type": "final_render",
        "status": "rendered",
        "approved": approved,
        "created_at": utc_now(),
    }


def _write_fixture(config_root: Path) -> None:
    analytics = config_root / "analytics"
    renders = config_root / "out" / "post_editor" / "renders"
    renders_evil = config_root / "out" / "post_editor" / "renders_evil"
    source_dir = config_root / "content_inbox"
    for path in (analytics, renders, renders_evil, source_dir, config_root / "out" / "post_editor" / "previews", config_root / "out" / "post_editor" / "thumbnails"):
        path.mkdir(parents=True, exist_ok=True)
    source = source_dir / "original.mp4"
    source.write_bytes(b"original-media")
    safe_final = renders / "safe.mp4"
    outside_final = renders_evil / "bad.mp4"
    safe_final.write_bytes(b"edited-final")
    outside_final.write_bytes(b"bad-final")
    plans = [
        _plan("safe_plan", "safe_clip", "tiktok", "content_inbox/original.mp4", "out/post_editor/renders/safe.mp4"),
        _plan("outside_plan", "outside_clip", "tiktok", "content_inbox/original.mp4", "out/post_editor/renders_evil/bad.mp4"),
        _plan("source_equals_plan", "source_equals_clip", "tiktok", "out/post_editor/renders/safe.mp4", "out/post_editor/renders/safe.mp4"),
        _plan("unapproved_plan", "unapproved_clip", "tiktok", "content_inbox/original.mp4", "out/post_editor/renders/safe.mp4"),
    ]
    jobs = [_job("safe_plan", True), _job("outside_plan", True), _job("source_equals_plan", True), _job("unapproved_plan", False)]
    save_json_file(analytics / "edit_plans.json", {"plans": plans})
    save_json_file(analytics / "edit_jobs.json", {"jobs": jobs})
    save_json_file(analytics / "post_editing_recommendations.json", {"recommendations": []})


def main() -> int:
    scratch = ROOT / "out" / "editing_approval_safety_fixture" / "project"
    if scratch.exists():
        shutil.rmtree(scratch)
    _write_fixture(scratch)
    config = load_config(scratch)
    failures: list[str] = []

    manifest = build_editing_manifest(config)
    by_plan = {asset["plan_id"]: asset for asset in manifest["preview_manifest"]["assets"]}
    if by_plan["safe_plan"].get("status") == "export_ready":
        failures.append("unapproved asset was export_ready before edited export receipt")

    dry_export = export_edited_social_assets(config, dry_run=True)
    if dry_export.get("candidate_count") != 0:
        failures.append("unapproved asset became export candidate")

    blocked = approve_edited_asset(config, plan_id="outside_plan", platform="tiktok", scope="edited_social_export", dry_run=False)
    if blocked.get("status") != "blocked":
        failures.append("outside render approval was not blocked")

    mismatched = approve_edited_asset(config, asset_id=by_plan["safe_plan"]["asset_id"], platform="instagram_reels", scope="edited_social_export", dry_run=False)
    if mismatched.get("status") != "fail":
        failures.append("mismatched platform approval did not fail")

    preview_only = approve_edited_asset(config, plan_id="safe_plan", platform="tiktok", scope="preview_only", dry_run=False)
    build_editing_manifest(config)
    if build_editing_manifest(config)["preview_manifest"]["assets"][0].get("status") == "export_ready":
        failures.append("preview-only receipt allowed edited export")
    if preview_only.get("receipt_created") is not True:
        failures.append("preview-only receipt was not created for safe asset")

    final_receipt = approve_edited_asset(config, plan_id="safe_plan", platform="tiktok", scope="final_render", dry_run=False)
    if final_receipt.get("receipt_created") is not True:
        failures.append("final render receipt was not created")
    if build_editing_manifest(config)["preview_manifest"]["assets"][0].get("status") == "export_ready":
        failures.append("final render receipt alone allowed edited export")

    export_receipt = approve_edited_asset(config, plan_id="safe_plan", platform="tiktok", scope="edited_social_export", dry_run=False)
    if export_receipt.get("receipt_created") is not True:
        failures.append("edited social export receipt was not created")
    manifest = build_editing_manifest(config)
    by_plan = {asset["plan_id"]: asset for asset in manifest["preview_manifest"]["assets"]}
    if by_plan["safe_plan"].get("status") != "export_ready":
        failures.append("edited social export receipt did not unlock export_ready")

    reject_edited_asset(config, asset_id=by_plan["safe_plan"]["asset_id"], reason="fixture rejection", dry_run=False)
    manifest = build_editing_manifest(config)
    if {asset["plan_id"]: asset for asset in manifest["preview_manifest"]["assets"]}["safe_plan"].get("status") == "export_ready":
        failures.append("rejected asset remained export_ready")

    queue = build_editing_approval_queue(config)
    if queue["client_state"]["summary"].get("rejected", 0) < 1:
        failures.append("rejected asset was not reflected in approval queue")

    export_after_reject = export_edited_social_assets(config, dry_run=False, approve=True)
    export_root = scratch / "out" / "social_exports_edited"
    if export_after_reject.get("exported_count"):
        failures.append("rejected asset exported")
    if any(path.is_file() for path in export_root.rglob("*")) if export_root.exists() else False:
        failures.append("approved export copied rejected media")

    report = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "scratch_root": str(scratch.relative_to(ROOT)),
    }
    save_json_file(ROOT / "analytics" / "editing_approval_safety_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
