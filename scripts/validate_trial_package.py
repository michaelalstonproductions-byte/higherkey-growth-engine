#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


PRIVATE_MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v"}
FORBIDDEN_NAMES = {"runtime_state.db", "events.jsonl", "audit_log.jsonl"}
FORBIDDEN_DIRS = {"content_inbox", "clips", "queue", "analytics", "logs"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def validate_trial_package(root: Path, package_dir: Path, dry_run: bool = False) -> dict[str, object]:
    if not package_dir.is_absolute():
        package_dir = root / package_dir
    required = [
        "CLIENT_HANDOFF_GUIDE.md",
        "CLIENT_QUICK_START.md",
        "BETA_READINESS_CHECKLIST.md",
        "TRIAL_DELIVERY_CHECKLIST.md",
        "TRIAL_LIMITATIONS.md",
        "CLIENT_TRIAL_QA_SUMMARY.md",
        "latest_dmg_pointer.json",
        "app_info.json",
        "support_note.txt",
        "quick_start.txt",
        "trial_limitations.txt",
        "client_feedback_template.json",
    ]
    missing = [name for name in required if not (package_dir / name).exists()]
    forbidden_files: list[str] = []
    private_media: list[str] = []
    if package_dir.exists():
        for path in package_dir.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = set(path.relative_to(package_dir).parts)
            if path.name in FORBIDDEN_NAMES or relative_parts.intersection(FORBIDDEN_DIRS):
                forbidden_files.append(rel(path, root))
            if path.suffix.lower() in PRIVATE_MEDIA_EXTENSIONS:
                private_media.append(rel(path, root))

    pointer = {}
    pointer_path = package_dir / "latest_dmg_pointer.json"
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except Exception as error:
            pointer = {"error": str(error)}

    status = "pass" if not missing and not forbidden_files and not private_media else "fail"
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "dry_run": dry_run,
        "local_only": True,
        "package_dir": rel(package_dir, root),
        "required_files": required,
        "missing_files": missing,
        "forbidden_files": forbidden_files,
        "private_media_files": private_media,
        "runtime_db_included": any(path.endswith("runtime_state.db") for path in forbidden_files),
        "content_inbox_included": any("/content_inbox/" in f"/{path}/" for path in forbidden_files),
        "latest_dmg_pointer": pointer,
        "safe_to_share": status == "pass",
    }
    if not dry_run:
        analytics = root / "analytics"
        analytics.mkdir(parents=True, exist_ok=True)
        (analytics / "trial_package_validation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the client trial package for safe handoff.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--package-dir", default="out/trial_release", help="Trial package folder.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing analytics/trial_package_validation.json.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = validate_trial_package(root, Path(args.package_dir), dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
