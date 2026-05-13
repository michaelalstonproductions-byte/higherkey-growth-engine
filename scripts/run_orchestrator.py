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
from growth_engine.orchestrator import run_orchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the HigherKey local multi-agent orchestrator")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--task", default="default", help="Task label stored in agent activity.")
    parser.add_argument("--once", action="store_true", help="Run one deterministic sequential pass and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Write agent state files without executing wrapped tasks.")
    args = parser.parse_args()

    config = load_config(Path(args.root))
    summary = run_orchestrator(config, task=args.task, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
