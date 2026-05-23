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
from growth_engine.editing_manifest import verify_editing_safety
from growth_engine.index import relative_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify non-destructive editing output safety.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    report = verify_editing_safety(config)
    summary = {
        "status": report["status"],
        "checked_assets": report["checked_assets"],
        "failure_count": len(report["failures"]),
        "original_media_protected": report["original_media_protected"],
        "source_overwrite_allowed": report["source_overwrite_allowed"],
        "editing_safety_report": relative_path(config.analytics_dir / "editing_safety_report.json", config.root),
    }
    print(json.dumps(summary if args.json else report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
