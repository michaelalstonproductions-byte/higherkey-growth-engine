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
from growth_engine.project_lifecycle import archive_project_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old/test HigherKey project artifacts without deleting by default.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--dry-run", action="store_true", help="Report archive candidates without moving files.")
    args = parser.parse_args()
    report = archive_project_artifacts(load_config(Path(args.root).resolve()), dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
