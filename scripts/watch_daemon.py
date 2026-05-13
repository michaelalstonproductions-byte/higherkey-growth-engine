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
from growth_engine.jobs import daemon_tick, run_daemon


def main() -> int:
    parser = argparse.ArgumentParser(description="HigherKey local watcher daemon")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run one daemon tick and exit.")
    parser.add_argument("--retry-failed", action="store_true", help="Move failed jobs back into retrying state.")
    parser.add_argument("--dry-run", action="store_true", help="Queue and report without processing a job.")
    args = parser.parse_args()

    config = load_config(Path(args.root))
    if args.dry_run:
        from growth_engine.jobs import enqueue_new_videos, apply_retry_requests, write_api_contract

        write_api_contract(config)
        summary = {
            "queued": enqueue_new_videos(config),
            "retry_requests": apply_retry_requests(config, retry_failed=args.retry_failed),
            "processed_job": None,
            "dry_run": True,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.once:
        print(json.dumps(daemon_tick(config, retry_failed=args.retry_failed), indent=2, sort_keys=True))
        return 0

    run_daemon(config, interval_seconds=args.interval, retry_failed=args.retry_failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
