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
from growth_engine.editing_delivery import build_editing_delivery_room
from growth_engine.index import relative_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local Edited Asset Delivery Room.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(Path.cwd())
    result = build_editing_delivery_room(config)
    summary = {
        "status": result["room"]["status"],
        "item_count": len(result["room"]["items"]),
        "ready_for_review": result["client_state"]["summary"]["ready_for_review"],
        "approved_for_delivery": result["client_state"]["summary"]["approved_for_delivery"],
        "editing_delivery_room": relative_path(config.analytics_dir / "editing_delivery_room.json", config.root),
        "editing_delivery_manifest": relative_path(config.analytics_dir / "editing_delivery_manifest.json", config.root),
        "client_editing_delivery_state": relative_path(config.analytics_dir / "client_editing_delivery_state.json", config.root),
        "editing_delivery_checklist": relative_path(config.analytics_dir / "editing_delivery_checklist.json", config.root),
    }
    print(json.dumps(summary if args.json else {**summary, "client_summary": result["client_state"]["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
