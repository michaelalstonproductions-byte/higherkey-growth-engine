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
from growth_engine.editing_delivery import record_editing_delivery_note


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a local edited asset delivery note.")
    parser.add_argument("--asset-id")
    parser.add_argument("--status", choices=["approved", "rejected", "needs_revision", "delivered"], default="approved")
    parser.add_argument("--note", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(Path.cwd())
    result = record_editing_delivery_note(
        config,
        asset_id=args.asset_id,
        status=args.status,
        note=args.note,
        dry_run=not args.write or args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
