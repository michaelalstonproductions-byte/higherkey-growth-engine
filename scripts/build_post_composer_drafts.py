#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.social_scheduler import build_post_composer_drafts


def main() -> None:
    config = load_config(Path.cwd())
    payload = build_post_composer_drafts(config)
    print(json.dumps({
        "status": "pass",
        "draft_count": payload.get("count", 0),
        "path": "analytics/post_composer_drafts.json",
        "manual_upload_fallback": True,
        "live_api_default": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
