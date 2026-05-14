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
from growth_engine.project_lifecycle import reset_demo_workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely reset generated demo/runtime outputs.")
    parser.add_argument("--root", default=".", help="Project root.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--soft", action="store_true", help="Clear generated outputs and keep content_inbox.")
    mode.add_argument("--hard", action="store_true", help="Clear generated outputs and source inbox only with confirmation.")
    parser.add_argument("--archive-first", action="store_true", help="Run backup before reset.")
    parser.add_argument("--confirm-delete-source-media", action="store_true", help="Required for hard reset.")
    parser.add_argument("--dry-run", action="store_true", help="Validate reset without deleting or moving files.")
    args = parser.parse_args()
    report = reset_demo_workspace(
        load_config(Path(args.root).resolve()),
        mode="hard" if args.hard else "soft",
        archive_first=args.archive_first,
        confirm_delete_source_media=args.confirm_delete_source_media,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
