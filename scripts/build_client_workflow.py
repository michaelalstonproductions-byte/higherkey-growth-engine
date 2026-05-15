#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.events import append_event
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file


STEP_ORDER = [
    "import_footage",
    "process_media",
    "review_clips",
    "approve_clips",
    "export_social_packs",
    "upload_manually",
]

STEP_LABELS = {
    "import_footage": "Import Footage",
    "process_media": "Process Media",
    "review_clips": "Review Clips",
    "approve_clips": "Approve Best Clips",
    "export_social_packs": "Export Social Packs",
    "upload_manually": "Upload Manually",
}


def _queue_entries(root: Path) -> list[dict[str, Any]]:
    payload = load_json_file(root / "queue" / "review_queue.json", {"entries": []})
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    return entries if isinstance(entries, list) else []


def _is_test_entry(entry: dict[str, Any]) -> bool:
    text = " ".join(str(entry.get(key, "")) for key in ("id", "clip_id", "source_path", "clip_path", "package_path")).lower()
    markers = ("smoke_sample", "smoke-test", "smoke_test", "testsrc", "colorbar", "color_bar", "fixture", "_test.", "-test.")
    return any(marker in text for marker in markers) or " smoke" in text or " test " in f" {text} "


def _count_approved(entries: list[dict[str, Any]]) -> int:
    return sum(1 for entry in entries if str(entry.get("status") or entry.get("review_status") or "").lower() == "approved")


def _social_count(root: Path) -> int:
    manifest = load_json_file(root / "out" / "social_exports" / "manifest.json", {})
    if isinstance(manifest, dict):
        return int(manifest.get("count") or len(manifest.get("exports", []) or []) or 0)
    return 0


def build_workflow(root: Path) -> dict[str, Any]:
    config = load_config(root)
    entries = _queue_entries(config.root)
    production_entries = [entry for entry in entries if not _is_test_entry(entry)]
    approved_count = _count_approved(production_entries)
    social_count = _social_count(config.root)
    client_state = load_json_file(config.analytics_dir / "client_state.json", {})
    client_tasks = load_json_file(config.analytics_dir / "client_tasks.json", {})
    client_metrics = load_json_file(config.analytics_dir / "client_metrics.json", {})
    client_integrity = load_json_file(config.analytics_dir / "client_integrity.json", {})
    client_storage = load_json_file(config.analytics_dir / "client_storage.json", {})

    completed = {
        "import_footage": bool(production_entries),
        "process_media": bool(production_entries),
        "review_clips": bool(production_entries),
        "approve_clips": approved_count > 0,
        "export_social_packs": social_count > 0,
        "upload_manually": False,
    }
    current_step = next((step for step in STEP_ORDER if not completed[step]), STEP_ORDER[-1])
    if social_count > 0:
        current_step = "upload_manually"

    warnings: list[str] = []
    for payload in (client_state, client_metrics, client_integrity, client_storage):
        summary = payload.get("warnings_summary") if isinstance(payload, dict) else None
        if isinstance(summary, list):
            warnings.extend(str(item) for item in summary if item)
    for payload, label in ((client_integrity, "Project integrity needs attention."), (client_storage, "Storage cleanup is recommended.")):
        status = str(payload.get("status") or "").lower() if isinstance(payload, dict) else ""
        if status in {"warn", "needs_attention"} and label not in warnings:
            warnings.append(label)

    task_stage = client_tasks.get("current_stage") or client_tasks.get("current_task") if isinstance(client_tasks, dict) else None
    processing = bool(task_stage and str(task_stage).lower() not in {"idle", "none", "null"})
    next_action = STEP_LABELS[current_step]
    if processing:
        next_action = "Wait for processing to finish"

    clip_count = len(production_entries)
    if not clip_count:
        client_message = "Import real footage to begin."
    elif current_step == "approve_clips":
        client_message = f"{clip_count} clips are ready. Approve the best clips for social export."
    elif current_step == "export_social_packs":
        client_message = f"{approved_count} approved clips are ready for social packs."
    elif current_step == "upload_manually":
        client_message = f"{social_count} social export pack sets are ready for manual upload."
    elif processing:
        client_message = "Processing media. HigherKey is preparing clips, previews, and recommendations."
    else:
        client_message = "Review clips and prepare manual social export packs."

    steps = [
        {
            "id": step,
            "label": STEP_LABELS[step],
            "status": "completed" if completed[step] else ("current" if step == current_step else "next"),
            "completed": completed[step],
        }
        for step in STEP_ORDER
    ]
    workflow = {
        "version": 1,
        "local_only": True,
        "last_updated": utc_now(),
        "current_step": current_step,
        "steps": steps,
        "completed_steps": [step for step in STEP_ORDER if completed[step]],
        "next_action": next_action,
        "client_message": client_message,
        "warnings_summary": list(dict.fromkeys(warnings))[:6],
        "counts": {
            "production_clips": clip_count,
            "approved_clips": approved_count,
            "social_export_packs": social_count,
            "hidden_test_media": max(0, len(entries) - clip_count),
        },
        "processing": {
            "active": processing,
            "stage": task_stage or "idle",
            "message": client_tasks.get("client_message") if isinstance(client_tasks, dict) else None,
            "progress_percentage": client_tasks.get("progress_percentage") if isinstance(client_tasks, dict) else None,
        },
        "demo_checklist": [
            {"label": "Import one real video", "completed": bool(production_entries)},
            {"label": "Run processing", "completed": bool(production_entries)},
            {"label": "Approve one clip", "completed": approved_count > 0},
            {"label": "Export social packs", "completed": social_count > 0},
            {"label": "Open export folder", "completed": social_count > 0},
        ],
    }
    save_json_file(config.analytics_dir / "client_workflow.json", workflow)
    append_event(config, "diagnostics.completed", severity="info", source="build_client_workflow", summary={"current_step": current_step, "next_action": next_action})
    return workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Build client-facing HigherKey workflow state.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    workflow = build_workflow(Path(args.root).resolve())
    print(json.dumps({"status": "pass", "client_workflow": "analytics/client_workflow.json", "workflow": workflow}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
