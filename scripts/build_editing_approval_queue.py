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
from growth_engine.editing_approval import build_editing_approval_queue
from growth_engine.index import relative_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the AI Editing Approval Console queue.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = build_editing_approval_queue(config)
    summary = {
        "status": result["queue"]["status"],
        "item_count": len(result["queue"]["items"]),
        "receipt_count": len(result["receipts"]["receipts"]),
        "editing_approval_queue": relative_path(config.analytics_dir / "editing_approval_queue.json", config.root),
        "editing_approval_receipts": relative_path(config.analytics_dir / "editing_approval_receipts.json", config.root),
        "client_editing_approval_state": relative_path(config.analytics_dir / "client_editing_approval_state.json", config.root),
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps({**summary, "client_summary": result["client_state"]["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
