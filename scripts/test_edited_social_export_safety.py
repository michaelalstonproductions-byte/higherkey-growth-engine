#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.editing_manifest import build_editing_manifest, export_edited_social_assets
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _plan(plan_id: str, clip_id: str, platform: str, source: str, render: str) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "clip_id": clip_id,
        "platform": platform,
        "source_path": source,
        "preview_path": f"out/post_editor/previews/{plan_id}.mp4",
        "render_path": render,
        "thumbnail_path": f"out/post_editor/thumbnails/{plan_id}.png",
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "created_at": "2026-05-22T00:00:00+00:00",
    }


def _job(plan_id: str, clip_id: str, approved: bool = True) -> dict[str, Any]:
    return {
        "job_id": f"job_{plan_id}",
        "type": "final_render",
        "plan_id": plan_id,
        "clip_id": clip_id,
        "status": "rendered",
        "approved": approved,
        "final_render_requires_approval": True,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
    }


def main() -> int:
    repo_config = load_config(Path.cwd())
    run_id = hashlib.sha1(utc_now().encode("utf-8")).hexdigest()[:10]
    scratch_root = repo_config.root / "out" / "edited_export_safety_fixture" / run_id
    config = load_config(scratch_root)
    analytics = config.analytics_dir
    export_root = config.root / "out" / "social_exports_edited"
    render_root = config.root / "out" / "post_editor" / "renders"
    failures: list[str] = []

    source = config.root / "content_inbox" / "edited_export_safety_source.mp4"
    safe_final = render_root / "safe_fixture.mp4"
    traversal_final = config.root / "out" / "post_editor" / "renders_evil" / "bad_fixture.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    safe_final.parent.mkdir(parents=True, exist_ok=True)
    traversal_final.parent.mkdir(parents=True, exist_ok=True)
    analytics.mkdir(parents=True, exist_ok=True)
    for path in (source, safe_final, traversal_final):
        path.write_bytes(b"fixture")

    plans = [
        _plan("safe_plan", "safe_clip", "tiktok", _rel(source, config.root), _rel(safe_final, config.root)),
        _plan("platform_traversal", "clip_platform", "../evil", _rel(source, config.root), _rel(safe_final, config.root)),
        _plan("clip_traversal", "../evil", "tiktok", _rel(source, config.root), _rel(safe_final, config.root)),
        _plan("absolute_segments", "/tmp/evil", "/tmp/platform", _rel(source, config.root), _rel(safe_final, config.root)),
        _plan("external_final", "external_clip", "tiktok", _rel(source, config.root), "/etc/hosts"),
        _plan("sibling_prefix_final", "sibling_clip", "tiktok", _rel(source, config.root), _rel(traversal_final, config.root)),
        _plan("source_equals_final", "source_equals_clip", "tiktok", _rel(safe_final, config.root), _rel(safe_final, config.root)),
        _plan("unapproved_final", "unapproved_clip", "tiktok", _rel(source, config.root), _rel(safe_final, config.root)),
    ]
    jobs = [
        _job("safe_plan", "safe_clip", True),
        _job("platform_traversal", "clip_platform", True),
        _job("clip_traversal", "../evil", True),
        _job("absolute_segments", "/tmp/evil", True),
        _job("external_final", "external_clip", True),
        _job("sibling_prefix_final", "sibling_clip", True),
        _job("source_equals_final", "source_equals_clip", True),
        _job("unapproved_final", "unapproved_clip", False),
    ]
    save_json_file(analytics / "edit_plans.json", {"plans": plans})
    save_json_file(analytics / "edit_jobs.json", {"jobs": jobs})
    save_json_file(analytics / "post_composer_drafts.json", {"drafts": []})

    initial_manifest = build_editing_manifest(config)
    initial_by_id = {asset["plan_id"]: asset for asset in initial_manifest["preview_manifest"]["assets"]}
    receipts = []
    for plan_id in ("safe_plan", "platform_traversal", "clip_traversal", "absolute_segments"):
        asset = initial_by_id[plan_id]
        receipts.append(
            {
                "receipt_id": f"fixture_receipt_{plan_id}",
                "approval_id": f"fixture_approval_{plan_id}",
                "asset_id": asset["asset_id"],
                "plan_id": asset["plan_id"],
                "clip_id": asset["clip_id"],
                "platform": asset["platform"],
                "approved_by": "local_operator",
                "approved_at": utc_now(),
                "approval_scope": "edited_social_export",
                "original_media_protected": True,
                "source_overwrite_allowed": False,
                "output_path": asset["final_render_path"],
                "status": "approved",
            }
        )
    save_json_file(analytics / "editing_approval_receipts.json", {"status": "pass", "receipts": receipts})

    manifest = build_editing_manifest(config)
    by_id = {asset["plan_id"]: asset for asset in manifest["preview_manifest"]["assets"]}
    if by_id["safe_plan"]["status"] != "export_ready":
        failures.append("safe approved render was not export_ready")
    for plan_id in ("external_final", "sibling_prefix_final", "source_equals_final", "unapproved_final"):
        if by_id[plan_id]["status"] == "export_ready":
            failures.append(f"{plan_id} incorrectly became export_ready")
    if by_id["external_final"].get("final_render_path_contained") is not False:
        failures.append("external final render was not marked uncontained")
    if by_id["sibling_prefix_final"].get("final_render_path_contained") is not False:
        failures.append("sibling-prefix final render was not marked uncontained")
    if by_id["source_equals_final"].get("source_equals_final_render") is not True:
        failures.append("source-equals-final was not detected")

    before = sorted(path for path in export_root.rglob("*")) if export_root.exists() else []
    dry = export_edited_social_assets(config, dry_run=True, approve=False)
    after = sorted(path for path in export_root.rglob("*")) if export_root.exists() else []
    if before != after:
        failures.append("dry-run wrote files under edited social exports")
    if dry.get("dry_run") is not True:
        failures.append("dry-run result did not report dry_run true")

    approved = export_edited_social_assets(config, dry_run=False, approve=True)
    if approved.get("status") != "pass":
        failures.append("approved export did not return pass")
    for item in approved.get("exports", []):
        folder = config.root / item.get("folder", "")
        media = config.root / item.get("media", "")
        if not _inside(folder, export_root) or not _inside(media, export_root):
            failures.append("approved export escaped out/social_exports_edited")
        if not (folder / "edit_manifest.json").exists():
            failures.append("approved export missing edit_manifest.json")
        if not (folder / "original_protection_proof.json").exists():
            failures.append("approved export missing original_protection_proof.json")
    evil_sibling = config.root / "out" / "social_exports_edited_evil"
    if evil_sibling.exists():
        failures.append("sibling-prefix edited export folder was created")

    report = {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "scratch_root": _rel(scratch_root, repo_config.root),
        "export_root": _rel(export_root, config.root),
        "render_root": _rel(render_root, config.root),
        "original_media_protected": True,
        "source_overwrite_allowed": False,
    }
    save_json_file(repo_config.analytics_dir / "edited_social_export_safety_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
