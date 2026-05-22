#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.media_editor import _outputs, _safe_output, build_edit_plan, create_final_render_job, create_preview_job


def check(condition: bool, name: str, failures: list[str]) -> None:
    if not condition:
        failures.append(name)


def rejects(callable_obj, name: str, failures: list[str]) -> None:
    try:
        callable_obj()
    except ValueError:
        return
    failures.append(name)


def main() -> int:
    config = load_config(Path.cwd())
    outputs = _outputs(config)
    failures: list[str] = []

    source = config.root / "content_inbox" / "media_editor_safety_source.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    before = source.read_bytes() if source.exists() else None
    if not source.exists():
        source.write_bytes(b"higherkey-media-editor-safety-source")
    source_mtime = source.stat().st_mtime_ns
    source_size = source.stat().st_size

    try:
        check(
            _safe_output(config, "out/post_editor/previews/safe_preview.mp4", outputs["previews"], "fallback.mp4", source).parent == outputs["previews"].resolve(),
            "safe_preview_output_rejected",
            failures,
        )
        check(
            _safe_output(config, "out/post_editor/renders/safe_render.mp4", outputs["renders"], "fallback.mp4", source).parent == outputs["renders"].resolve(),
            "safe_render_output_rejected",
            failures,
        )
        check(
            _safe_output(config, "out/post_editor/thumbnails/safe_thumb.png", outputs["thumbnails"], "fallback.png", source).parent == outputs["thumbnails"].resolve(),
            "safe_thumbnail_output_rejected",
            failures,
        )

        rejects(lambda: _safe_output(config, "out/post_editor/renders_evil/file.mp4", outputs["renders"], "fallback.mp4", source), "sibling_prefix_not_rejected", failures)
        rejects(lambda: _safe_output(config, "out/post_editor/renders/../outside/file.mp4", outputs["renders"], "fallback.mp4", source), "traversal_not_rejected", failures)
        rejects(lambda: _safe_output(config, "/tmp/higherkey_external_render.mp4", outputs["renders"], "fallback.mp4", source), "external_absolute_not_rejected", failures)
        rejects(lambda: _safe_output(config, str(source), outputs["renders"], "fallback.mp4", source), "source_equal_output_not_rejected", failures)

        plan_result = build_edit_plan(config, video=str(source), platform="tiktok", notes="safety fixture", dry_run=True)
        plan_id = plan_result["plan"]["plan_id"]
        preview_result = create_preview_job(config, plan_id=plan_id, dry_run=True)
        final_without_approval = create_final_render_job(config, plan_id=plan_id, approve=False, dry_run=False)
        final_dry_run = create_final_render_job(config, plan_id=plan_id, approve=False, dry_run=True)

        check(preview_result["job"]["status"] == "preview_ready_dry_run", "preview_dry_run_status_wrong", failures)
        check(final_without_approval["job"]["status"] == "approval_required", "final_without_approval_not_blocked", failures)
        check(final_dry_run["job"]["status"] == "final_render_dry_run", "final_dry_run_status_wrong", failures)
        check(not (config.root / final_dry_run["job"]["output_path"]).exists(), "dry_run_wrote_final_media", failures)
        check(source.stat().st_mtime_ns == source_mtime and source.stat().st_size == source_size, "original_media_modified", failures)
    finally:
        if before is None:
            try:
                source.unlink()
            except FileNotFoundError:
                pass
        else:
            source.write_bytes(before)

    result = {
        "status": "fail" if failures else "pass",
        "failures": failures,
        "original_media_protected": not failures or "original_media_modified" not in failures,
        "source_overwrite_allowed": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
