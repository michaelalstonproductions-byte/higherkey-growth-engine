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
from growth_engine.json_store import save_json_file
from growth_engine.task_queue import list_schedules, upsert_schedule


DEFAULT_SCHEDULES = (
    ("daily_maintenance", "maintenance", "daily", "low"),
    ("hourly_runtime_snapshot", "build_runtime_snapshot", "hourly", "normal"),
    ("startup_media_repair", "repair_project_media", "startup", "high"),
    ("metadata_refresh", "rebuild_metadata_index", "daily", "normal"),
    ("diagnostics_check", "run_diagnostics", "daily", "normal"),
    ("social_export_refresh", "export_social_packs", "manual", "low"),
    ("color_school_refresh", "run_color_school", "manual", "low"),
    ("audio_school_refresh", "run_audio_school", "manual", "low"),
)


def schedule(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    config = load_config(root)
    schedules = []
    for schedule_id, task_type, cadence, priority in DEFAULT_SCHEDULES:
        payload = {"schedule_id": schedule_id, "cadence": cadence}
        if dry_run:
            schedules.append({"schedule_id": schedule_id, "task_type": task_type, "cadence": cadence, "priority": priority, "payload": payload, "enabled": True})
        else:
            schedules.append(upsert_schedule(config, schedule_id, task_type, cadence, payload, priority=priority))
    if not dry_run:
        schedules = list_schedules(config)
        save_json_file(config.analytics_dir / "task_schedules.json", {"version": 1, "updated_at": utc_now(), "schedules": schedules, "local_only": True})
    return {"version": 1, "updated_at": utc_now(), "status": "pass", "dry_run": dry_run, "schedules": schedules, "local_only": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create local HigherKey task schedules.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", help="Preview schedules without writing SQLite rows.")
    args = parser.parse_args()
    result = schedule(Path(args.root).resolve(), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
