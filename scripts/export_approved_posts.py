#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.exporter import export_approved_posts


def main() -> int:
    parser = argparse.ArgumentParser(description="Export approved HigherKey posts to local files")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--queue", default=None, help="Review queue JSON path. Defaults to queue/review_queue.json.")
    parser.add_argument("--approvals", default=None, help="Approved reviews JSON path. Defaults to queue/approved_reviews.json.")
    parser.add_argument("--output", default=None, help="Output directory. Defaults to out/approved_posts.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summary = export_approved_posts(
        root=root,
        queue_path=Path(args.queue).resolve() if args.queue else None,
        approvals_path=Path(args.approvals).resolve() if args.approvals else None,
        output_dir=Path(args.output).resolve() if args.output else None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
