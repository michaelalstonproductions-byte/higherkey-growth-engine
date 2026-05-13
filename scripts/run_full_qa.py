#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.analytics import save_json
from growth_engine.config import load_config
from growth_engine.diagnostics import command_result, run_diagnostics, summarize_report
from growth_engine.index import relative_path, utc_now


EXCLUDED_DIRS = {"node_modules", "dist", ".git", "__pycache__", "analytics", "out", "clips", "captions", "queue", "content_inbox", "logs"}
SCAN_PATTERN = re.compile(r"https?://|fetch\(|axios|openai|api\.|graph\.facebook|instagram|tiktok|youtube|twitter|x\.com|cloud|social", re.IGNORECASE)


def dashboard_js_check(root: Path) -> dict[str, object]:
    script = (
        "const fs=require('fs');"
        "const html=fs.readFileSync('dashboard/review.html','utf8');"
        "const scripts=[...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]);"
        "for (const script of scripts) new Function(script);"
        "console.log(JSON.stringify({scripts:scripts.length}));"
    )
    return command_result("dashboard_js_syntax", ["node", "-e", script], root, timeout=30)


def packaged_path_check(root: Path) -> dict[str, object]:
    resources = root / "dist" / "mac-arm64" / "HigherKey Operator OS.app" / "Contents" / "Resources"
    if not resources.exists():
        return {"name": "packaged_path_verification", "status": "warn", "message": "dist:dir output not found"}
    required = [
        resources / "app.asar",
        resources / "app-assets" / "dashboard" / "review.html",
        resources / "app-assets" / "growth_engine" / "diagnostics.py",
        resources / "app-assets" / "growth_engine" / "media_cache.py",
        resources / "app-assets" / "scripts" / "run_full_qa.py",
        resources / "app-assets" / "scripts" / "build_media_cache.py",
    ]
    forbidden = [resources / "app-assets" / name for name in ("analytics", "queue", "clips", "captions", "out", "logs", "content_inbox")]
    missing = [relative_path(path, root) for path in required if not path.exists()]
    present_forbidden = [relative_path(path, root) for path in forbidden if path.exists()]
    status = "pass" if not missing and not present_forbidden else "fail"
    return {
        "name": "packaged_path_verification",
        "status": status,
        "missing": missing,
        "forbidden_runtime_dirs": present_forbidden,
    }


def external_api_scan(root: Path) -> dict[str, object]:
    hits = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name == "package-lock.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if SCAN_PATTERN.search(line):
                hits.append({"path": relative_path(path, root), "line": line_no, "text": line.strip()[:220]})
    risky = [
        hit
        for hit in hits
        if not (
            "README.md" in hit["path"]
            or "scripts/run_full_qa.py" in hit["path"]
            or "No cloud" in hit["text"]
            or "no cloud" in hit["text"]
            or "localhost" in hit["text"]
            or "127.0.0.1" in hit["text"]
            or "fetch(`${path}" in hit["text"]
            or "w3.org" in hit["text"]
            or "platform_notes" in hit["text"]
            or "manual upload" in hit["text"].lower()
            or "posting integration" in hit["text"].lower()
            or "social export" in hit["text"].lower()
            or "social_export" in hit["text"].lower()
            or ("social" in hit["text"].lower() and "api" not in hit["text"].lower())
            or "instagram" in hit["text"].lower()
            or "tiktok" in hit["text"].lower()
            or "youtube" in hit["text"].lower()
            or "youtube_shorts" in hit["text"].lower()
        )
    ]
    return {"name": "external_api_scan", "status": "pass" if not risky else "fail", "hits": hits, "risky_hits": risky}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey full local QA")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip the heavier smoke test.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config = load_config(root)
    results: list[dict[str, object]] = []

    diagnostics = run_diagnostics(config)
    results.append({"name": "diagnostics", "status": diagnostics["status"], "summary": diagnostics.get("status")})
    results.append(command_result("py_compile", ["python3", "-m", "py_compile", *[str(path) for path in sorted(root.glob("growth_engine/*.py"))], *[str(path) for path in sorted(root.glob("scripts/*.py"))]], root))
    if not args.skip_smoke:
        results.append(command_result("smoke_test", ["python3", "scripts/smoke_test.py"], root, timeout=240))
    results.append(command_result("pipeline_once", ["python3", "scripts/run_pipeline.py"], root))
    results.append(command_result("daemon_once", ["python3", "scripts/watch_daemon.py", "--once"], root))
    results.append(command_result("orchestrator_once", ["python3", "scripts/run_orchestrator.py", "--once"], root))
    results.append(command_result("media_cache_build", ["python3", "scripts/build_media_cache.py", "--force", "--limit", "3"], root, timeout=180))
    results.append(dashboard_js_check(root))
    results.append(packaged_path_check(root))
    results.append(external_api_scan(root))

    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": summarize_report(results),
        "root": str(root),
        "results": results,
    }
    save_json(config.analytics_dir / "qa_report.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
