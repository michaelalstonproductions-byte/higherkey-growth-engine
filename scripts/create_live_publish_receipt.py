#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.live_publish_readiness import create_live_publish_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local live publish approval receipt.")
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--approved-by", default="local_operator")
    parser.add_argument("--confirmation-phrase", required=True)
    parser.add_argument("--dry-run-before-live", action="store_true")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()
    config = load_config(Path.cwd())
    payload = create_live_publish_receipt(
        config,
        draft_id=args.draft_id,
        platform=args.platform,
        approved_by=args.approved_by,
        confirmation_phrase=args.confirmation_phrase,
        dry_run_before_live=args.dry_run_before_live,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
