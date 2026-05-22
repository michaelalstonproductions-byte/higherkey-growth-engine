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
from growth_engine.index import relative_path
from growth_engine.media_editor import build_edit_plan
from growth_engine.post_editing_intelligence import build_post_editing_recommendations


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-destructive local post edit plan.")
    parser.add_argument("--clip-id")
    parser.add_argument("--image")
    parser.add_argument("--video")
    parser.add_argument("--platform", default="tiktok")
    parser.add_argument("--notes", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    recommendations = build_post_editing_recommendations(config, notes=args.notes)
    result = build_edit_plan(
        config,
        clip_id=args.clip_id,
        image=args.image,
        video=args.video,
        platform=args.platform,
        notes=args.notes,
        dry_run=True if args.dry_run else False,
    )
    summary = {
        "status": result["status"],
        "plan_id": result["plan"]["plan_id"],
        "clip_id": result["plan"].get("clip_id"),
        "source_exists": result["plan"].get("source_exists"),
        "non_destructive": result["plan"].get("non_destructive"),
        "original_media_protected": result["plan"].get("original_media_protected"),
        "recommendations": len(recommendations.get("recommendations", [])),
        "edit_plans": relative_path(config.analytics_dir / "edit_plans.json", config.root),
        "client_state": relative_path(config.analytics_dir / "client_editing_state.json", config.root),
    }
    print(json.dumps(summary if args.json else {**result, "recommendation_count": summary["recommendations"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
