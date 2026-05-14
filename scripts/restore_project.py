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
from growth_engine.project_lifecycle import restore_project


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a HigherKey project backup.")
    parser.add_argument("backup_path", help="Backup zip or folder path.")
    parser.add_argument("--root", default=".", help="Current project root for reporting.")
    parser.add_argument("--target", default=None, help="Target project folder. Defaults to current project.")
    parser.add_argument("--force", action="store_true", help="Allow restore into existing non-empty target.")
    parser.add_argument("--dry-run", action="store_true", help="Validate restore without writing files.")
    args = parser.parse_args()
    report = restore_project(load_config(Path(args.root).resolve()), Path(args.backup_path).resolve(), Path(args.target).resolve() if args.target else None, force=args.force, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
