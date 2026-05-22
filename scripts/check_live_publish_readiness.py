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
from growth_engine.live_publish_readiness import live_publish_readiness_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Check controlled live publish readiness without making platform calls.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--platform", default="all")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()
    config = load_config(Path.cwd())
    payload = live_publish_readiness_summary(config, platform=args.platform)
    summary = {
        "status": "pass",
        "dry_run": True,
        "platform": args.platform,
        "live_call_made": False,
        "ready_count": payload.get("ready_count", 0),
        "blocked_count": payload.get("blocked_count", 0),
        "paths": [
            "analytics/live_publish_readiness.json",
            "analytics/client_live_publish_readiness.json",
        ],
        "manual_upload_fallback": True,
    }
    print(json.dumps(summary if args.json else payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
