#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.client_success_delivery import build_client_success_presentation
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build client success presentation overview docs.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write presentation markdown.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_client_success_presentation(config, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
