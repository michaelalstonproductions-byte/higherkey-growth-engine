#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANNED_TERMS = [
    "stdout",
    "stderr",
    "cwd",
    "SQLite",
    "runtime DB",
    "task queue",
    "schema",
    "ffprobe",
    "raw JSON",
    "local API",
]
CLIENT_FILES = [
    "dashboard/review.html",
    "CLIENT_QUICK_START.md",
    "CLIENT_HANDOFF_GUIDE.md",
    "TRIAL_LIMITATIONS.md",
    "TRIAL_DELIVERY_CHECKLIST.md",
    "CLIENT_TRIAL_QA_SUMMARY.md",
]
ALLOWED_CONTEXT = re.compile(
    r"diagnostic|setting|advanced|support|readme|technical|runtime|qa|preflight|projectRuntimeHtml|desktopBridgeHtml",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    findings: list[dict[str, object]] = []
    for relative in CLIENT_FILES:
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            lower = line.lower()
            for term in BANNED_TERMS:
                if term.lower() in lower:
                    context_start = max(0, line_no - 12)
                    context_end = min(len(lines), line_no + 12)
                    context = "\n".join(lines[context_start:context_end])
                    allowed = bool(ALLOWED_CONTEXT.search(line)) or bool(ALLOWED_CONTEXT.search(context)) or "README" in path.name
                    findings.append({
                        "path": rel(path),
                        "line": line_no,
                        "term": term,
                        "allowed_context": allowed,
                        "text": line.strip()[:220],
                    })
    blocking = [item for item in findings if not item["allowed_context"]]
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "pass" if not blocking else "warn",
        "local_only": True,
        "checked_files": CLIENT_FILES,
        "banned_terms": BANNED_TERMS,
        "findings": findings,
        "blocking_findings": blocking,
        "summary": {
            "findings": len(findings),
            "blocking_findings": len(blocking),
            "note": "Technical terms are acceptable in Support, Settings, Diagnostics, README, and Advanced contexts.",
        },
    }
    analytics = ROOT / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "client_language_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
