#!/usr/bin/env python3
"""Generate local release notes for the HigherKey Operator OS desktop demo."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_CONFIG = ROOT / "config" / "release.json"
OUTPUT = ROOT / "RELEASE_NOTES.md"


def read_release_config() -> dict:
    if not RELEASE_CONFIG.exists():
        return {
            "product_name": "HigherKey Operator OS",
            "version": "V2.7",
            "build_status": "release-candidate",
            "app_id": "com.higherkey.operatoros",
            "local_first_statement": "HigherKey Operator OS runs locally. No cloud APIs or social APIs are configured.",
        }
    return json.loads(RELEASE_CONFIG.read_text(encoding="utf-8"))


def git_log(limit: int = 12) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--oneline"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def notes_markdown(release: dict, commits: list[str]) -> str:
    product = release.get("product_name", "HigherKey Operator OS")
    version = release.get("version", "V2.7")
    status = release.get("build_status", "release-candidate")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    local_first = release.get(
        "local_first_statement",
        "HigherKey Operator OS runs locally. No cloud APIs or social APIs are configured.",
    )
    recent_commits = "\n".join(f"- `{line}`" for line in commits) or "- Git history unavailable during generation."
    return f"""# {product} {version} Release Notes

Generated: {generated_at}

Build status: `{status}`

App id: `{release.get("app_id", "com.higherkey.operatoros")}`

{local_first}

## V2.7 Release Candidate Desktop Demo

- Added startup splash screen for the Electron desktop shell.
- Added first-run setup flow for project folder, content inbox, FFmpeg health, diagnostics, and Operator UI handoff.
- Added About panel metadata, version badge, Open Content Inbox, and Run First Pipeline controls.
- Added release notes generation and demo checklist artifacts for repeatable desktop demonstrations.
- Added final app icon replacement notes and release build checklist documentation.

## Preserved Capabilities

- V1 local video ingest, clip generation, captions, queue review, and approved export workflow.
- V1.5 through V1.9 local content intelligence, metadata, learning, watcher daemon, and pipeline status JSON.
- V2.0 through V2.2 Electron shell, Operator workstation UI, live local JSON polling, recommendations, and comparisons.
- V2.3 deterministic local multi-agent orchestration.
- V2.4 packaged macOS desktop distribution using writable runtime project paths.
- V2.5 FFmpeg-based media preview cache.
- V2.6 diagnostics, safe JSON recovery, and one-command QA.

## Verification Checklist

- `npm run electron:verify`
- `npm run dist:dir`
- `npm run qa:full`
- `python3 -m py_compile growth_engine/*.py scripts/*.py`
- `python3 scripts/smoke_test.py`
- `python3 scripts/run_diagnostics.py`
- `python3 scripts/generate_release_notes.py`
- Dashboard JavaScript syntax check
- Packaged app/path verification
- External API scan

## Recent Git History

{recent_commits}
"""


def main() -> int:
    release = read_release_config()
    commits = git_log()
    OUTPUT.write_text(notes_markdown(release, commits), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(OUTPUT.relative_to(ROOT)),
        "version": release.get("version", "V2.7"),
        "commit_count": len(commits),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
