#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import ensure_directories, load_config
from growth_engine.events import append_event
from growth_engine.index import utc_now
from growth_engine.json_store import load_json_file, save_json_file
from growth_engine.runtime_db import db_path, init_db


def project_id(root: Path) -> str:
    return "project_" + hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:12]


def init_manifest(root: Path) -> dict[str, object]:
    prevented_content_inbox_root = root.name == "content_inbox"
    if root.name == "content_inbox":
        root = root.parent
    config = load_config(root)
    ensure_directories(config)
    init_db(config)
    manifest_path = config.root / "config" / "project_manifest.json"
    existing = load_json_file(manifest_path, {})
    now = utc_now()
    manifest = {
        "version": 1,
        "project_id": existing.get("project_id") or project_id(config.root),
        "project_name": existing.get("project_name") or config.root.name,
        "project_root": str(config.root),
        "content_inbox": str(config.inbox_dir),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "runtime_db": str(db_path(config)),
        "local_only": True,
    }
    save_json_file(manifest_path, manifest)
    status = {
        "version": 1,
        "updated_at": now,
        "status": "pass",
        "manifest_path": "config/project_manifest.json",
        "project_root": str(config.root),
        "content_inbox": str(config.inbox_dir),
        "runtime_db": str(db_path(config)),
        "prevented_content_inbox_root": prevented_content_inbox_root,
        "local_only": True,
    }
    save_json_file(config.analytics_dir / "project_manifest_status.json", status)
    append_event(config, "project.selected", severity="info", source="init_project_manifest", summary=status)
    return {"manifest": manifest, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize HigherKey project manifest and runtime paths.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    result = init_manifest(Path(args.root).resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
