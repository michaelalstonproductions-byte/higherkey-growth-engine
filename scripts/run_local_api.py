#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.local_api import DEFAULT_HOST, DEFAULT_PORT, load_project_config, once_health, run_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey local-only API service")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host. Must be 127.0.0.1 or localhost.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port. Defaults to 8765.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--once-health", action="store_true", help="Run a bounded health check and exit.")
    parser.add_argument("--write-status", action="store_true", help="Write analytics/local_api_status.json.")
    args = parser.parse_args()

    config = load_project_config(Path(args.root).resolve())
    if args.once_health:
        payload = once_health(config, host=args.host, port=args.port, write_status_file=True)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1

    run_server(config, host=args.host, port=args.port, write_status_file=True if args.write_status else True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
