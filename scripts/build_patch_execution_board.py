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
from growth_engine.patch_execution import build_patch_execution_board


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local patch execution board from the trial patch plan.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write patch execution outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_patch_execution_board(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "patch_execution_board": "analytics/patch_execution_board.json",
        "patch_verification_plan": "analytics/patch_verification_plan.json",
        "client_patch_status": "analytics/client_patch_status.json",
        "patch_execution_board_md": "out/client_delivery/PATCH_EXECUTION_BOARD.md",
        "patch_verification_checklist_md": "out/client_delivery/PATCH_VERIFICATION_CHECKLIST.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
