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
from growth_engine.editing_approval import reject_edited_asset


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject an edited asset or mark it for revision without deleting media.")
    parser.add_argument("--asset-id")
    parser.add_argument("--reason", default="rejected")
    parser.add_argument("--notes", default="")
    parser.add_argument("--needs-revision", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true", help="Write the rejection record. Without this, the command is a dry-run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = reject_edited_asset(
        config,
        asset_id=args.asset_id,
        reason=args.reason,
        notes=args.notes,
        needs_revision=args.needs_revision,
        dry_run=not args.write or args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
