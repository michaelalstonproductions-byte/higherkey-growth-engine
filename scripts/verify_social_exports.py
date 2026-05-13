#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.social_exports import PLATFORM_KEYS, export_social_packs


REQUIRED_FILES = {
    "caption.txt",
    "hashtags.txt",
    "title.txt",
    "posting_notes.txt",
    "upload_checklist.txt",
    "manifest.json",
}


def main() -> int:
    queue_path = ROOT / "queue" / "review_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    entries = queue.get("entries", [])
    if not entries:
      raise SystemExit("queue/review_queue.json has no entries to verify")
    approved = entries[0]["id"]
    summary = export_social_packs(ROOT, platforms=list(PLATFORM_KEYS), approved_id_values=[approved])
    if summary["count"] != len(PLATFORM_KEYS):
        raise SystemExit(f"expected {len(PLATFORM_KEYS)} exports, got {summary['count']}")
    for item in summary["exports"]:
        pack_dir = ROOT / item["video"]
        pack_dir = pack_dir.parent
        missing = sorted(name for name in REQUIRED_FILES if not (pack_dir / name).exists())
        if missing:
            raise SystemExit(f"missing files for {item['platform']}: {missing}")
        if item.get("direct_posting_apis") is not False or item.get("manual_upload_only") is not True:
            raise SystemExit(f"manual upload flags incorrect for {item['platform']}")
    history_path = ROOT / "analytics" / "social_export_history.json"
    if not history_path.exists():
        raise SystemExit("analytics/social_export_history.json was not written")
    print(json.dumps({
        "status": "pass",
        "approved_entry_id": approved,
        "platforms": list(PLATFORM_KEYS),
        "exported": summary["count"],
        "manifest_path": "out/social_exports/manifest.json",
        "history_path": "analytics/social_export_history.json"
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
