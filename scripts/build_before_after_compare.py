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
from growth_engine.editing_manifest import build_before_after_compare
from growth_engine.index import relative_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build before/after comparison metadata without changing media.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = build_before_after_compare(config)
    summary = {
        "status": result["status"],
        "record_count": len(result["records"]),
        "media_modified": result["media_modified"],
        "before_after_compare": relative_path(config.analytics_dir / "before_after_compare.json", config.root),
    }
    print(json.dumps(summary if args.json else result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
