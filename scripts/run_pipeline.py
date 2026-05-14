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
from growth_engine.events import append_event
from growth_engine.pipeline import process_once, watch


def main() -> int:
    parser = argparse.ArgumentParser(description="HigherKey local growth engine pipeline")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--watch", action="store_true", help="Poll content_inbox continuously.")
    parser.add_argument("--interval", type=float, default=5.0, help="Watch polling interval in seconds.")
    args = parser.parse_args()

    config = load_config(Path(args.root))
    if args.watch:
        watch(config, args.interval)
        return 0

    append_event(config, "pipeline.started", severity="info", source="run_pipeline", summary={"watch": False})
    summary = process_once(config)
    severity = summary.get("severity", "pass")
    event_type = "pipeline.completed"
    if severity == "needs_attention":
        event_type = "pipeline.needs_attention"
    elif severity == "fail":
        event_type = "pipeline.failed"
    append_event(config, event_type, severity=severity, source="run_pipeline", summary=summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary.get("severity") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
