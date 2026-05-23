#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.client_delivery import build_client_delivery_manifest
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build client delivery and launch readiness manifests.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect readiness without writing outputs.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()
    config = load_config(Path.cwd())
    result = build_client_delivery_manifest(config, dry_run=args.dry_run)
    summary = {
        "status": result["readiness"]["status"],
        "client_delivery_manifest": "analytics/client_delivery_manifest.json",
        "client_launch_readiness": "analytics/client_launch_readiness.json",
        "client_delivery_checklist": "analytics/client_delivery_checklist.json",
        "client_delivery_readme": "out/client_delivery/CLIENT_DELIVERY_README.md",
        "client_delivery_checklist_md": "out/client_delivery/CLIENT_DELIVERY_CHECKLIST.md",
        "ready_count": result["readiness"]["ready_count"],
        "needs_attention_count": result["readiness"]["needs_attention_count"],
        "missing_count": result["readiness"]["missing_count"],
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary if args.json else result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
