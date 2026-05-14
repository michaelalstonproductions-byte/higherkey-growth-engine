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
from growth_engine.project_lifecycle import project_size_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HigherKey project size report.")
    parser.add_argument("--root", default=".", help="Project root.")
    args = parser.parse_args()
    report = project_size_report(load_config(Path(args.root).resolve()))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
