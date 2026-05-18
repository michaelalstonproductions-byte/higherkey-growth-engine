#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_EXTENSIONS = {".mp4", ".mov", ".m4v"}
FORBIDDEN_PACKAGE_NAMES = {"runtime_state.db", "events.jsonl", "audit_log.jsonl"}
FORBIDDEN_PACKAGE_DIRS = {"content_inbox", "clips", "captions", "logs", "media_cache"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check(name: str, passed: bool, message: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "status": "pass" if passed else "fail",
        "message": message,
    }
    payload.update(extra)
    return payload


def has_bridge_method(preload: str, main: str, exposed: str, ipc: str) -> bool:
    return exposed in preload and ipc in preload and ipc in main


def package_scan(package_dir: Path) -> dict[str, object]:
    forbidden: list[str] = []
    private_media: list[str] = []
    if package_dir.exists():
        for path in package_dir.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.relative_to(package_dir).parts)
            if path.name in FORBIDDEN_PACKAGE_NAMES or parts.intersection(FORBIDDEN_PACKAGE_DIRS):
                forbidden.append(rel(path))
            if path.suffix.lower() in PRIVATE_EXTENSIONS:
                private_media.append(rel(path))
    return {"forbidden": forbidden, "private_media": private_media}


def support_package_scan(package_dir: Path) -> dict[str, object]:
    forbidden: list[str] = []
    if package_dir.exists():
        for path in package_dir.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.relative_to(package_dir).parts)
            if path.name in FORBIDDEN_PACKAGE_NAMES or parts.intersection({"content_inbox", "clips", "captions", "social_exports"}):
                forbidden.append(rel(path))
            if path.suffix.lower() in PRIVATE_EXTENSIONS:
                forbidden.append(rel(path))
    return {"forbidden": sorted(set(forbidden))}


def version_alignment(root: Path) -> dict[str, object]:
    package = load_json(root / "package.json", {})
    lock = load_json(root / "package-lock.json", {})
    release = load_json(root / "config" / "release.json", {})
    contract = load_json(root / "config" / "version_contract.json", {})
    package_version = str(package.get("version") if isinstance(package, dict) else "")
    release_version = str(release.get("version") if isinstance(release, dict) else "")
    expected_dmg = root / "dist" / f"HigherKey Operator OS-{package_version}-arm64.dmg"
    lock_versions = []
    if isinstance(lock, dict):
        lock_versions.append(str(lock.get("version", "")))
        root_package = lock.get("packages", {}).get("", {}) if isinstance(lock.get("packages"), dict) else {}
        lock_versions.append(str(root_package.get("version", "")))
    version_parts = package_version.split(".") if package_version else []
    expected_release = ""
    if len(version_parts) >= 3 and version_parts[2] == "0":
        expected_release = f"V{version_parts[0]}.{version_parts[1]}"
    elif package_version:
        expected_release = f"V{package_version}"
    aligned = (
        bool(package_version)
        and release_version == expected_release
        and all(version == package_version for version in lock_versions if version)
        and isinstance(contract, dict)
        and contract.get("app_version") == package_version
        and contract.get("release_version") == release_version
    )
    return {
        "aligned": aligned,
        "package_version": package_version,
        "release_version": release_version,
        "lock_versions": lock_versions,
        "dmg_path": rel(expected_dmg),
        "dmg_exists": expected_dmg.exists(),
    }


def main() -> int:
    analytics = ROOT / "analytics"
    preload = text(ROOT / "electron" / "preload.js")
    main_js = text(ROOT / "electron" / "main.js")
    dashboard = text(ROOT / "dashboard" / "review.html")
    readme = text(ROOT / "README.md")
    quick_start = text(ROOT / "CLIENT_QUICK_START.md")
    limitations = text(ROOT / "TRIAL_LIMITATIONS.md")
    handoff = text(ROOT / "CLIENT_HANDOFF_GUIDE.md")
    trial_checklist = text(ROOT / "TRIAL_DELIVERY_CHECKLIST.md")
    package_dir = ROOT / "out" / "trial_release"
    support_dir = ROOT / "out" / "client_issue_report"
    package_result = package_scan(package_dir)
    support_result = support_package_scan(support_dir)
    version = version_alignment(ROOT)
    trial_validation = load_json(analytics / "trial_package_validation.json", {})
    readiness = load_json(analytics / "trial_readiness_report.json", {})
    workflow = load_json(analytics / "client_workflow.json", {})

    manual_text = "\n".join([dashboard, readme, quick_start, limitations, handoff, trial_checklist]).lower()
    direct_posting_pattern = re.compile(r"(direct posting|posting api|social api|cloud api)", re.I)
    direct_posting_mentions = direct_posting_pattern.findall(manual_text)
    no_direct_posting = (
        "manual upload" in manual_text
        and ("no direct posting" in manual_text or "does not post directly" in manual_text)
        and "no cloud" in manual_text
    )

    checks = [
        check("version_alignment", bool(version["aligned"]), "Package, release, lockfile, and contract versions align.", **version),
        check("dmg_target", bool(version["dmg_path"]), "Expected DMG target is known.", path=version["dmg_path"], exists=version["dmg_exists"]),
        check("client_quick_start", bool(quick_start), "CLIENT_QUICK_START.md exists."),
        check("trial_limitations", bool(limitations), "TRIAL_LIMITATIONS.md exists."),
        check("handoff_guide", bool(handoff), "CLIENT_HANDOFF_GUIDE.md exists."),
        check("trial_delivery_checklist", bool(trial_checklist), "TRIAL_DELIVERY_CHECKLIST.md exists."),
        check("support_package_workflow", (ROOT / "scripts" / "create_issue_report.py").exists(), "Support package script exists."),
        check("feedback_workflow", (ROOT / "scripts" / "collect_client_feedback.py").exists(), "Local feedback script exists."),
        check("client_workflow_json", bool(workflow), "analytics/client_workflow.json exists.", current_step=workflow.get("current_step") if isinstance(workflow, dict) else None),
        check("trial_readiness_report", bool(readiness), "analytics/trial_readiness_report.json exists.", overall=readiness.get("overall_readiness") if isinstance(readiness, dict) else None),
        check("import_bridge", has_bridge_method(preload, main_js, "importFootage", "files:importFootage"), "Import Footage bridge is exposed."),
        check("import_process_bridge", has_bridge_method(preload, main_js, "importAndProcessFootage", "files:importAndProcessFootage"), "Import & Process bridge is exposed."),
        check("social_export_bridge", has_bridge_method(preload, main_js, "exportSocialPacks", "social:exportPacks"), "Social export bridge is exposed."),
        check("support_package_bridge", has_bridge_method(preload, main_js, "createIssueReport", "support:createIssueReport"), "Support package bridge is exposed."),
        check("trial_package_private_media", not package_result["private_media"], "Trial package contains no private media.", private_media=package_result["private_media"]),
        check("trial_package_forbidden_runtime", not package_result["forbidden"], "Trial package excludes runtime DB/log/media folders.", forbidden=package_result["forbidden"]),
        check("support_package_client_safe", not support_result["forbidden"], "Support package excludes private media and runtime DB by default.", forbidden=support_result["forbidden"]),
        check("trial_package_validation", isinstance(trial_validation, dict) and trial_validation.get("status") == "pass", "Trial package validation passes.", status=trial_validation.get("status") if isinstance(trial_validation, dict) else None),
        check("manual_upload_language", no_direct_posting, "Client docs and UI state manual upload with no cloud/social posting APIs.", direct_posting_mentions=direct_posting_mentions[:10]),
    ]
    failures = [item for item in checks if item["status"] == "fail"]
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "social_apis": False,
        "direct_posting_apis": False,
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
        "summary": {
            "passed": len(checks) - len(failures),
            "failed": len(failures),
            "dmg_path": version["dmg_path"],
            "trial_package": rel(package_dir),
            "support_package": rel(support_dir),
        },
    }
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "client_trial_qa_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
