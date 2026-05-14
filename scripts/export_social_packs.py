#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.social_exports import PLATFORM_KEYS, export_social_packs
from growth_engine.config import load_config
from growth_engine.events import append_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local manual-upload platform export packs")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--platform", action="append", choices=PLATFORM_KEYS, help="Platform to export. Repeatable. Defaults to all.")
    parser.add_argument("--approvals", default=None, help="Approved reviews JSON path. Defaults to queue/approved_reviews.json.")
    parser.add_argument("--approved-id", action="append", default=[], help="Approved queue entry id or clip id. Repeatable.")
    parser.add_argument("--output", default=None, help="Output directory. Defaults to out/social_exports.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summary = export_social_packs(
        root=root,
        platforms=args.platform,
        approvals_path=Path(args.approvals).resolve() if args.approvals else None,
        approved_id_values=args.approved_id,
        output_dir=Path(args.output).resolve() if args.output else None,
    )
    append_event(load_config(root), "social_export.generated", severity="fail" if summary.get("errors") else "info", source="export_social_packs", summary=summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not summary.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
