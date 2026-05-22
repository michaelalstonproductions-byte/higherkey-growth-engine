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
from growth_engine.media_editor import create_final_render_job


def main() -> int:
    parser = argparse.ArgumentParser(description="Render or dry-run a final post asset. Final render requires approval.")
    parser.add_argument("--plan-id")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = create_final_render_job(config, plan_id=args.plan_id, approve=args.approve, dry_run=True if args.dry_run else False)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
