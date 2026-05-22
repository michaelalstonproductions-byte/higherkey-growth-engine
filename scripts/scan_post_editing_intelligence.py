#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import relative_path, utc_now
from growth_engine.json_store import save_json_file


KEYWORDS = {
    "reference image intelligence": ("reference image", "reference_image", "look reference"),
    "look matching": ("look match", "look_matching", "match look"),
    "cinematic plan": ("cinematic plan", "cinematic_plan"),
    "contact sheet builder": ("contact sheet", "contact_sheet"),
    "color school": ("color school", "color_school"),
    "audio school": ("audio school", "audio_school"),
    "visionqc": ("visionqc", "vision qc"),
    "restoration": ("restoration", "restore"),
    "safe preview render": ("safe preview", "preview render", "edit_preview"),
    "thumbnail generation": ("thumbnail", "thumb"),
    "caption overlay": ("caption overlay", "text overlay", "drawtext"),
    "ffmpeg editing": ("ffmpeg", "subprocess.run"),
    "ai director": ("ai director", "director"),
    "social post editing": ("social post", "post editor", "post_edit"),
}
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".json", ".md", ".sh", ".html", ".css", ".txt"}
SKIP_PARTS = {".git", "node_modules", "__pycache__", "dist", "analytics", "out", "clips", "captions", "queue", "logs", "content_inbox"}


def scan_file(path: Path) -> list[dict[str, object]]:
    text = ""
    if path.suffix.lower() in TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000].lower()
        except OSError:
            text = ""
    name_text = str(path).lower()
    haystack = f"{name_text}\n{text}"
    findings = []
    for label, needles in KEYWORDS.items():
        matched = [needle for needle in needles if needle in haystack]
        if matched:
            findings.append({"capability": label, "matched": matched[:3]})
    return findings


def iter_files(root: Path, limit: int) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        if len(files) >= limit:
            break
        current = Path(dirpath)
        try:
            rel_parts = current.relative_to(root).parts
        except ValueError:
            rel_parts = current.parts
        if any(part in SKIP_PARTS for part in rel_parts):
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in SKIP_PARTS]
        for filename in filenames:
            if len(files) >= limit:
                break
            path = current / filename
            if path.suffix.lower() != ".pdf":
                files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only scan for reusable local post-editing intelligence.")
    parser.add_argument("--dry-run", action="store_true", help="Keep scan read-only; still writes the local scan report.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    parser.add_argument("--limit", type=int, default=2500, help="Maximum files per root.")
    args = parser.parse_args()

    config = load_config(Path.cwd())
    codex_root = Path.home() / "Documents" / "Codex"
    resolve_app = codex_root / "2026-05-02-resolve-app"
    roots = [codex_root, Path("/Volumes"), config.root]
    searched = []
    findings = []
    for root in roots:
        root = root.expanduser()
        searched.append(str(root))
        for path in iter_files(root, args.limit):
            matches = scan_file(path)
            if not matches:
                continue
            try:
                display = str(path.relative_to(config.root))
            except ValueError:
                display = str(path)
            findings.append({"path": display, "matches": matches})

    report = {
        "status": "pass",
        "updated_at": utc_now(),
        "read_only": True,
        "dry_run": bool(args.dry_run),
        "searched_roots": searched,
        "specifically_scanned": str(resolve_app),
        "resolve_app_present": resolve_app.exists(),
        "files_with_findings": len(findings),
        "findings": findings[:300],
        "notes": "Scan is read-only and does not copy or modify external files.",
    }
    out = config.analytics_dir / "post_editing_intelligence_scan.json"
    save_json_file(out, report)
    summary = {"status": "pass", "findings": len(findings), "report": relative_path(out, config.root)}
    print(json.dumps(summary if args.json else report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
