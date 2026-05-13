#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.media_cache import build_media_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local FFmpeg media preview cache")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing preview assets.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queue entries to cache.")
    args = parser.parse_args()

    summary = build_media_cache(Path(args.root), force=args.force, limit=args.limit)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
