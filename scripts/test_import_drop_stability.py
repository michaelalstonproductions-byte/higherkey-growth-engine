#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check(name: str, passed: bool, message: str) -> dict[str, str]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "message": message,
    }


def main() -> int:
    dashboard = read(ROOT / "dashboard" / "review.html")
    main = read(ROOT / "electron" / "main.js")
    preload = read(ROOT / "electron" / "preload.js")
    checks = [
        check("global_dragover_prevent_default", "window.addEventListener(\"dragover\"" in dashboard and "event.preventDefault();" in dashboard, "Dashboard prevents browser navigation during dragover."),
        check("global_drop_prevent_default", "window.addEventListener(\"drop\"" in dashboard and "event.stopPropagation();" in dashboard, "Dashboard prevents browser navigation during drop."),
        check("drop_import_handler", "async function ingestDroppedFiles" in dashboard and "window.higherkey.ingestDroppedFiles(importPaths)" in dashboard, "Dropped files route through the intended import workflow."),
        check("drop_failure_client_safe", "Import failed safely" in dashboard and "Try Import Footage" in dashboard, "Drop failures keep the shell visible with client-safe copy."),
        check("renderer_error_capture", "window.onerror" in dashboard and "unhandledrejection" in dashboard and "recordRendererError" in dashboard, "Renderer errors are captured and surfaced safely."),
        check("renderer_fallback_panel", "Something went wrong, but HigherKey is still running." in dashboard and "Return to Command" in dashboard, "Renderer fallback panel exists."),
        check("preload_import_methods", all(token in preload for token in ("importFootage", "importAndProcessFootage", "ingestDroppedFiles", "getDroppedFilePaths", "recordRendererError")), "Preload exposes import/drop/error methods."),
        check("main_import_handlers", all(token in main for token in ("files:importFootage", "files:importAndProcessFootage", "files:ingestDropped", "renderer:recordError")), "Main process registers matching import/drop/error IPC handlers."),
        check("descriptor_path_normalization", "const inputPath = typeof filePath === \"string\" ? filePath : (filePath?.path || \"\")" in main, "Main process normalizes dropped file descriptors before path validation."),
        check("no_shell_import_command", "shell: true" not in main[main.find("async function importFootage"):main.find("async function runFullMediaPrep")], "Import path does not build shell-string commands."),
    ]
    failures = [item for item in checks if item["status"] != "pass"]
    report = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not failures else "fail",
        "local_only": True,
        "checks": checks,
    }
    out = ROOT / "analytics" / "import_drop_stability_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
