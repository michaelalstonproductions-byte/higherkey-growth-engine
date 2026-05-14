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
from growth_engine.diagnostics import run_diagnostics
from growth_engine.events import append_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey local diagnostics")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--skip-packaging", action="store_true", help="Skip packaged app path checks.")
    args = parser.parse_args()

    config = load_config(Path(args.root))
    payload = run_diagnostics(config, include_packaging=not args.skip_packaging)
    append_event(config, "diagnostics.completed", severity=payload.get("status", "info"), source="run_diagnostics", summary={"status": payload.get("status")})
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
