#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.cache_manager import archive_generated_artifacts, apply_cleanup_plan, build_cleanup_plan, measure_storage, vacuum_runtime_db
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage HigherKey local storage, retention, and cleanup plans.")
    parser.add_argument("command", choices=["report", "plan", "apply", "archive", "dry-run", "vacuum-db"], help="Storage command to run.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Run without altering files.")
    parser.add_argument("--apply", action="store_true", help="Allow apply mode for cleanup operations.")
    parser.add_argument("--category", default=None, help="Limit to one retention category.")
    parser.add_argument("--max-age-days", type=int, default=None, help="Override max age for planning.")
    parser.add_argument("--max-size-mb", type=int, default=None, help="Override max size for planning.")
    parser.add_argument("--confirm", action="store_true", help="Confirm file-altering storage operations.")
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    args = parser.parse_args()

    config = load_config(Path(args.root).resolve())
    dry_run = True if args.command in {"dry-run", "plan"} else args.dry_run
    if args.command == "report":
        payload = measure_storage(config)
    elif args.command in {"plan", "dry-run"}:
        payload = build_cleanup_plan(config, category=args.category, max_age_days=args.max_age_days, max_size_mb=args.max_size_mb, dry_run=True)
    elif args.command == "apply":
        payload = apply_cleanup_plan(config, confirm=args.confirm, category=args.category, dry_run=not args.apply)
    elif args.command == "archive":
        payload = archive_generated_artifacts(config, confirm=args.confirm, category=args.category, dry_run=not args.apply or dry_run)
    elif args.command == "vacuum-db":
        payload = vacuum_runtime_db(config, dry_run=not (args.apply and args.confirm))
    else:
        raise AssertionError(args.command)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
