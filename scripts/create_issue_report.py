#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEYS = {"token", "secret", "password", "auth", "authorization"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def redact(value: object) -> object:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in SENSITIVE_KEYS):
                result[key] = "[redacted]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def issue_report(root: Path, output: Path, dry_run: bool = False) -> dict[str, object]:
    output = output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()

    analytics = root / "analytics"
    source_files = {
        "diagnostics_summary.json": analytics / "diagnostics.json",
        "client_state.json": analytics / "client_state.json",
        "client_workflow.json": analytics / "client_workflow.json",
        "client_tasks.json": analytics / "client_tasks.json",
        "client_integrity.json": analytics / "client_integrity.json",
        "client_storage.json": analytics / "client_storage.json",
    }
    included = [name for name, source in source_files.items() if source.exists()]
    missing = [name for name, source in source_files.items() if not source.exists()]
    summary = {
        "created_at": utc_now(),
        "product": "HigherKey Operator OS",
        "local_only": True,
        "includes_original_footage": False,
        "includes_private_media": False,
        "includes_runtime_db": False,
        "included_files": included,
        "missing_optional_files": missing,
        "support_note": "This package is safe to share for support. It excludes source footage, generated clips, large logs, runtime DB files, and local tokens by default.",
    }
    text = "\n".join([
        "HigherKey Operator OS Client Issue Report",
        f"Created: {summary['created_at']}",
        "",
        "Included:",
        *[f"- {name}" for name in included],
        "",
        "Not included by default:",
        "- Original footage",
        "- Private generated media",
        "- Full logs",
        "- Runtime database",
        "- Local tokens or secrets",
        "",
        "Client note:",
        "Describe what happened, what you expected, and which step you were on.",
        "",
    ])

    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "issue_report.json", summary)
        (output / "issue_report.txt").write_text(text, encoding="utf-8")
        for name, source in source_files.items():
            if source.exists():
                write_json(output / name, redact(load_json(source, {})))

    return {
        "status": "pass",
        "dry_run": dry_run,
        "output": str(output),
        "included": ["issue_report.json", "issue_report.txt", *included],
        "missing_optional_files": missing,
        "local_only": True,
        "private_media_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a client-safe local issue report package.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--output", default="out/client_issue_report", help="Output folder.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned report contents without writing.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    print(json.dumps(issue_report(root, Path(args.output), dry_run=args.dry_run), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
