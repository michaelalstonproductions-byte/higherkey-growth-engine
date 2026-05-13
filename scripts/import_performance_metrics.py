#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.analytics import import_performance_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local manual performance metrics")
    parser.add_argument("import_path", help="JSON file containing manual performance records.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--history", default=None, help="Optional performance history output path.")
    args = parser.parse_args()

    summary = import_performance_metrics(
        root=Path(args.root),
        import_path=Path(args.import_path),
        history_path=Path(args.history) if args.history else None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
