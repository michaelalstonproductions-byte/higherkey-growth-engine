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
        check("capture_dragover_prevent_default", "window.addEventListener(\"dragover\", hkPreventDropNavigation, true)" in dashboard and "document.addEventListener(\"dragover\", hkPreventDropNavigation, true)" in dashboard, "Dashboard installs capture-phase dragover prevention."),
        check("capture_drop_prevent_default", "window.addEventListener(\"drop\", hkHandleCapturedDrop, true)" in dashboard and "document.addEventListener(\"drop\", hkHandleCapturedDrop, true)" in dashboard and "event.stopPropagation();" in dashboard, "Dashboard prevents browser navigation during captured drop."),
        check("body_root_drop_backup", "document.body?.addEventListener(\"drop\", hkHandleCapturedDrop, true)" in dashboard and "document.querySelector(\".hk-shell\")?.addEventListener(\"drop\", hkHandleCapturedDrop, true)" in dashboard, "Body and app shell have backup drop handlers."),
        check("drop_import_handler", "async function ingestDroppedFiles" in dashboard and "window.higherkey.ingestDroppedFiles(importInputs)" in dashboard, "Dropped files route through the intended import workflow."),
        check("drop_failure_client_safe", "Import failed safely" in dashboard and "Try Import Footage" in dashboard, "Drop failures keep the shell visible with client-safe copy."),
        check("renderer_error_capture", "window.onerror" in dashboard and "unhandledrejection" in dashboard and "recordRendererError" in dashboard, "Renderer errors are captured and surfaced safely."),
        check("renderer_fallback_panel", "Something went wrong, but HigherKey is still running." in dashboard and "Return to Command" in dashboard and "Reload App" in dashboard, "Renderer fallback panel exists."),
        check("render_recovery_wrapper", "function render()" in dashboard and "showShellRecovery(\"HigherKey recovered from a screen rendering error." in dashboard, "Render has a recovery wrapper."),
        check("unsupported_drop_safe_message", "choose a supported media file" in dashboard and "No supported footage files were dropped." in main, "Unsupported drops show a safe message."),
        check("folder_drop_safe_message", "Folder drops are not supported yet. Use Import Footage to choose media files." in main, "Folder drops show a visible safe message."),
        check("preload_import_methods", all(token in preload for token in ("importFootage", "importAndProcessFootage", "ingestDroppedFiles", "getDroppedFilePaths", "recordRendererError")), "Preload exposes import/drop/error methods."),
        check("main_import_handlers", all(token in main for token in ("files:importFootage", "files:importAndProcessFootage", "files:ingestDropped", "renderer:recordError")), "Main process registers matching import/drop/error IPC handlers."),
        check("main_navigation_guards", all(token in main for token in ("will-navigate", "will-redirect", "did-fail-load", "setWindowOpenHandler", "blocked_window_navigation")), "Main process blocks unexpected file/external navigation."),
        check("descriptor_path_normalization", "const inputPath = typeof filePath === \"string\" ? filePath : (filePath?.path || \"\")" in main, "Main process normalizes dropped file descriptors before path validation."),
        check("structured_import_result", all(token in main for token in ("imported_count", "skipped_count", "unsupported_count", "client_message")), "Import/drop IPC returns structured client-safe result fields."),
        check("no_source_delete_or_overwrite", "unlink" not in main[main.find("async function ingestDroppedFiles"):main.find("async function recordRendererError")] and "rm " not in main[main.find("async function ingestDroppedFiles"):main.find("async function recordRendererError")], "Import/drop path does not delete or overwrite source media."),
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
