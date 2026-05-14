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
from growth_engine.task_queue import task_summary


def build_snapshot(root: Path) -> dict[str, object]:
    config = load_config(root)
    summary = task_summary(config)
    counts = summary["counts"]
    current = summary.get("current_task")
    next_task = summary.get("next_task")
    warnings = []
    if counts.get("failed"):
        warnings.append(f"{counts['failed']} task(s) failed.")
    if counts.get("blocked"):
        warnings.append(f"{counts['blocked']} task(s) waiting on dependencies.")
    client = {
        "version": 1,
        "last_updated": utc_now(),
        "current_task": current.get("task_type") if current else None,
        "current_stage": current.get("current_stage") or current.get("status") if current else "idle",
        "progress_percentage": summary.get("progress_percentage", 0),
        "queued_count": counts.get("queued", 0) + counts.get("scheduled", 0) + counts.get("retrying", 0) + counts.get("blocked", 0),
        "running_count": counts.get("running", 0),
        "completed_count": counts.get("completed", 0),
        "failed_count": counts.get("failed", 0),
        "client_message": current.get("client_message") if current else (next_task.get("client_message") if next_task else "No queued tasks."),
        "next_action": f"Run {next_task.get('task_type')}" if next_task else "No queued tasks",
        "warnings_summary": warnings,
        "local_only": True,
    }
    snapshot = {"version": 1, "updated_at": utc_now(), "summary": summary, "local_only": True}
    save_json_file(config.analytics_dir / "task_summary.json", snapshot)
    save_json_file(config.analytics_dir / "client_tasks.json", client)
    return {"status": "pass", "task_summary": "analytics/task_summary.json", "client_tasks": "analytics/client_tasks.json", "client": client}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build task queue snapshots.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    result = build_snapshot(Path(args.root).resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
