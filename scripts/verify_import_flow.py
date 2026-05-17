#!/usr/bin/env python3
"""Verify the local desktop import bridge wiring.

This is a static, bounded check for the client import workflow. It does not
launch Electron or open a native picker.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def has_all(text: str, needles: list[str]) -> bool:
    return all(needle in text for needle in needles)


def main() -> int:
    preload = read("electron/preload.js")
    main_js = read("electron/main.js")
    ingest = read("electron/ingest.js")

    checks = [
        {
            "name": "preload_import_methods",
            "ok": has_all(preload, ["importFootage", "importAndProcessFootage", "ingestDroppedFiles", "getDroppedFilePaths"]),
        },
        {
            "name": "main_import_ipc",
            "ok": has_all(main_js, ["files:importFootage", "files:importAndProcessFootage", "files:ingestDropped"]),
        },
        {
            "name": "native_file_picker",
            "ok": has_all(main_js, ["dialog.showOpenDialog", "openFile", "multiSelections"]),
        },
        {
            "name": "accepted_video_extensions",
            "ok": has_all(ingest + main_js, [".mp4", ".mov", ".m4v"]),
        },
        {
            "name": "safe_duplicate_names",
            "ok": has_all(ingest, ["uniqueInboxTarget", "while (true)", "copyFile", "index += 1"]),
        },
        {
            "name": "client_result_shape",
            "ok": has_all(main_js, ["importedFiles", "skipped", "errors", "inbox", "imported"]),
        },
        {
            "name": "full_media_prep_client_stages",
            "ok": has_all(main_js, ["run_color_school.py", "run_audio_school.py", "build_client_workflow.py"]),
        },
    ]
    ok = all(item["ok"] for item in checks)
    report = {
        "ok": ok,
        "status": "pass" if ok else "fail",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
    out = ROOT / "analytics" / "import_flow_verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
