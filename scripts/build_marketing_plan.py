#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.marketing_intelligence import build_marketing_intelligence, write_marketing_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local Marketing Intelligence Studio outputs.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = build_marketing_intelligence(root)
    markdown = write_marketing_markdown(root, result)
    summary = {
        "ok": True,
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "recommendations": len(result["marketing_recommendations"]),
        "analytics_outputs": [
            "analytics/marketing_brief.json",
            "analytics/audience_profile.json",
            "analytics/market_attack_plan.json",
            "analytics/content_strategy.json",
            "analytics/platform_strategy.json",
            "analytics/campaign_calendar.json",
            "analytics/marketing_recommendations.json",
        ],
        "markdown_outputs": markdown,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
