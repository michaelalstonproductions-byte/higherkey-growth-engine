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
from growth_engine.patch_execution import build_client_release_notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local client release notes from verified patch execution items.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write release note outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_client_release_notes(config, dry_run=args.dry_run)
    print(json.dumps({
        "status": result.get("status"),
        "dry_run": result.get("dry_run"),
        "patch_release_notes": "analytics/patch_release_notes.json",
        "client_release_notes": "analytics/client_release_notes.json",
        "client_release_notes_md": "out/client_delivery/CLIENT_RELEASE_NOTES.md",
        "client_update_message_md": "out/client_delivery/CLIENT_UPDATE_MESSAGE.md",
        "internal_patch_notes_md": "out/client_delivery/INTERNAL_PATCH_NOTES.md",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
