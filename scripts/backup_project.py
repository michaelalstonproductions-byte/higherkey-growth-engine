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
from growth_engine.project_lifecycle import backup_project


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local HigherKey project backup.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--include-source-media", action="store_true", help="Include content_inbox media.")
    parser.add_argument("--include-cache", action="store_true", help="Include generated media cache.")
    parser.add_argument("--folder", action="store_true", help="Write folder snapshot instead of zip.")
    parser.add_argument("--dry-run", action="store_true", help="Validate backup contents without writing archive.")
    args = parser.parse_args()
    report = backup_project(load_config(Path(args.root).resolve()), include_source_media=args.include_source_media, include_cache=args.include_cache, dry_run=args.dry_run, as_folder=args.folder)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
