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
from growth_engine.editing_manifest import build_editing_manifest
from growth_engine.index import relative_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local AI Editing Preview QA manifests.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    result = build_editing_manifest(config)
    summary = {
        "status": result["preview_manifest"]["status"],
        "asset_count": len(result["preview_manifest"]["assets"]),
        "export_ready_count": result["edited_asset_manifest"]["export_ready_count"],
        "editing_preview_manifest": relative_path(config.analytics_dir / "editing_preview_manifest.json", config.root),
        "edited_asset_manifest": relative_path(config.analytics_dir / "edited_asset_manifest.json", config.root),
        "client_editing_manifest": relative_path(config.analytics_dir / "client_editing_manifest.json", config.root),
    }
    print(json.dumps(summary if args.json else {**summary, "client_summary": result["client_manifest"]["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
