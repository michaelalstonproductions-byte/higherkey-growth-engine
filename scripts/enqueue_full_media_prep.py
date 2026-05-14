#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.task_queue import add_dependency, enqueue_task


CHAIN = (
    "repair_project_media",
    "run_pipeline",
    "rebuild_metadata_index",
    "build_media_cache",
    "run_color_school",
    "run_audio_school",
    "run_orchestrator",
    "build_runtime_snapshot",
)


def build_chain(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    config = load_config(root)
    tasks = []
    previous_id = None
    for task_type in CHAIN:
        payload = {"chain": "full_media_prep", "created_by": "enqueue_full_media_prep"}
        if task_type in {"run_color_school", "run_audio_school"}:
            payload["quick"] = False
        if task_type == "build_media_cache":
            payload["limit"] = None
        if dry_run:
            task = {
                "task_id": f"dry_{len(tasks) + 1}_{task_type}",
                "task_type": task_type,
                "status": "queued",
                "depends_on": previous_id,
                "payload": payload,
            }
        else:
            task = enqueue_task(config, task_type, payload, priority="normal", source="full_media_prep")
            if previous_id:
                add_dependency(config, task["task_id"], previous_id)
                task["depends_on"] = previous_id
        previous_id = task["task_id"]
        tasks.append(task)
    return {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass",
        "dry_run": dry_run,
        "chain": "full_media_prep",
        "tasks": tasks,
        "local_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue a dependent Full Media Prep task chain.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", help="Preview task chain without writing to SQLite.")
    args = parser.parse_args()
    summary = build_chain(Path(args.root).resolve(), dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
