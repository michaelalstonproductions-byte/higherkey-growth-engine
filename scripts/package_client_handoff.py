#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def latest_dmg_name(package_version: str) -> str:
    return f"HigherKey Operator OS-{package_version}-arm64.dmg"


def package_handoff(root: Path, output: Path, dry_run: bool = False) -> dict[str, object]:
    package = load_json(root / "package.json", {})
    release = load_json(root / "config" / "release.json", {})
    package_version = str(package.get("version") or "4.5.0")
    release_version = str(release.get("version") or "V4.5")
    dmg_path = root / "dist" / latest_dmg_name(package_version)
    output = output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()

    files = {
        "CLIENT_HANDOFF_GUIDE.md": root / "CLIENT_HANDOFF_GUIDE.md",
        "BETA_READINESS_CHECKLIST.md": root / "BETA_READINESS_CHECKLIST.md",
        "DEMO_CHECKLIST.md": root / "DEMO_CHECKLIST.md",
        "RELEASE_NOTES.md": root / "RELEASE_NOTES.md",
    }
    app_info = {
        "product": "HigherKey Operator OS",
        "package_version": package_version,
        "release_version": release_version,
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "social_apis": False,
    }
    pointer = {
        "expected_dmg": str(dmg_path.relative_to(root)),
        "exists": dmg_path.exists(),
        "package_version": package_version,
        "release_version": release_version,
        "note": "The handoff package points to the latest DMG but does not copy it by default.",
    }
    quick_start = "\n".join([
        "HigherKey Operator OS Quick Start",
        "1. Open the newest DMG from dist/.",
        "2. Launch HigherKey Operator OS.",
        "3. Click Import Footage.",
        "4. Click Import & Process or Process Media.",
        "5. Review clips and export social packs.",
        "6. Upload prepared files manually.",
        "",
    ])
    support_note = "\n".join([
        "HigherKey Operator OS Support Note",
        "",
        "For beta support, use Create Support Package from the app or run:",
        "python3 scripts/create_issue_report.py",
        "",
        "The support package excludes original footage, generated media, runtime DB files, and local tokens by default.",
        "Feedback can be captured locally with:",
        "python3 scripts/collect_client_feedback.py",
        "",
    ])

    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
        for name, source in files.items():
            if source.exists():
                shutil.copy2(source, output / name)
        (output / "app_info.json").write_text(json.dumps(app_info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "latest_dmg_pointer.json").write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "quick_start.txt").write_text(quick_start, encoding="utf-8")
        (output / "support_note.txt").write_text(support_note, encoding="utf-8")

    return {
        "status": "pass",
        "dry_run": dry_run,
        "local_only": True,
        "output": str(output),
        "included": [name for name, source in files.items() if source.exists()] + ["app_info.json", "latest_dmg_pointer.json", "quick_start.txt", "support_note.txt"],
        "latest_dmg_pointer": pointer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a client handoff package without copying private runtime data.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--output", default="out/client_handoff", help="Output folder.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing files.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = package_handoff(root, Path(args.output), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
