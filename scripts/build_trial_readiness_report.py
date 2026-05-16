#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback: Optional[dict] = None) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback or {}


def latest_dmg_name(version: str) -> str:
    return f"HigherKey Operator OS-{version}-arm64.dmg"


def status_from(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            nested = status_from(value, "status", "overall", "health")
            if nested != "unknown":
                return nested
        if value is not None:
            text = str(value).lower()
            if text in {"pass", "passed", "ready", "healthy", "secure", "aligned"}:
                return "pass"
            if text in {"warn", "warning", "needs_attention", "needs attention", "cleanup recommended"}:
                return "warn"
            if text in {"fail", "failed", "not_ready", "not ready", "unsafe", "error"}:
                return "fail"
            return text
    return "unknown"


def summarize_component(name: str, status: str, message: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def build_report(root: Path) -> dict[str, object]:
    package = load_json(root / "package.json")
    release = load_json(root / "config" / "release.json")
    version = str(package.get("version") or "4.7.0")
    release_version = str(release.get("version") or "V4.7")
    dmg_path = root / "dist" / latest_dmg_name(version)

    analytics = root / "analytics"
    client_workflow = load_json(analytics / "client_workflow.json")
    diagnostics = load_json(analytics / "diagnostics.json")
    qa_report = load_json(analytics / "qa_report.json")
    launch_preflight = load_json(analytics / "launch_preflight.json")
    security = load_json(analytics / "security_report.json")
    storage = load_json(analytics / "client_storage.json")
    integrity = load_json(analytics / "client_integrity.json")
    trial_validation = load_json(analytics / "trial_package_validation.json")
    feedback_summary = load_json(analytics / "client_feedback_summary.json")
    client_trial_qa = load_json(analytics / "client_trial_qa_report.json")
    client_language = load_json(analytics / "client_language_report.json")

    docs = [
        "CLIENT_HANDOFF_GUIDE.md",
        "CLIENT_QUICK_START.md",
        "BETA_READINESS_CHECKLIST.md",
        "DEMO_CHECKLIST.md",
        "RELEASE_NOTES.md",
        "TRIAL_LIMITATIONS.md",
        "TRIAL_DELIVERY_CHECKLIST.md",
        "CLIENT_TRIAL_QA_SUMMARY.md",
    ]
    doc_status = {name: (root / name).exists() for name in docs}
    trial_package = root / "out" / "trial_release"
    trial_files = [
        "quick_start.txt",
        "app_info.json",
        "latest_dmg_pointer.json",
        "support_note.txt",
        "trial_limitations.txt",
        "client_feedback_template.json",
    ]
    trial_file_status = {name: (trial_package / name).exists() for name in trial_files}

    components = [
        summarize_component("dmg", "pass" if dmg_path.exists() else "warn", str(dmg_path.relative_to(root))),
        summarize_component("client_workflow", "pass" if client_workflow.get("current_step") else "warn", str(client_workflow.get("current_step") or "not generated")),
        summarize_component("diagnostics", status_from(diagnostics, "status"), "Latest local diagnostics status."),
        summarize_component("qa", status_from(qa_report, "status"), "Latest full QA status."),
        summarize_component("launch_preflight", status_from(launch_preflight, "status", "overall_readiness"), "Launch preflight status."),
        summarize_component("security", status_from(security, "status", "overall"), "Local security status."),
        summarize_component("storage", status_from(storage, "status", "storage_status"), "Local storage status."),
        summarize_component("integrity", status_from(integrity, "status", "integrity_status"), "State integrity status."),
        summarize_component("handoff_docs", "pass" if all(doc_status.values()) else "fail", "Required trial docs present."),
        summarize_component("trial_package", "pass" if trial_package.exists() and all(trial_file_status.values()) else "warn", "Trial package can be generated with scripts/package_trial_release.py."),
        summarize_component("trial_package_validation", status_from(trial_validation, "status"), "Client trial package validation status."),
        summarize_component("feedback_workflow", "pass" if (root / "scripts" / "collect_client_feedback.py").exists() else "fail", "Local feedback capture script."),
        summarize_component("feedback_summary", "pass" if feedback_summary else "warn", "Latest local feedback summary."),
        summarize_component("support_package_capability", "pass" if (root / "scripts" / "create_issue_report.py").exists() else "fail", "Client-safe support package script."),
        summarize_component("version_alignment", "pass" if release_version.lstrip("V") in version or version.startswith(release_version.lstrip("V")) else "warn", "package.json and config/release.json version alignment."),
        summarize_component("client_trial_qa", status_from(client_trial_qa, "status"), "Final client trial QA report status."),
        summarize_component("client_language", status_from(client_language, "status"), "Client-facing language scan status."),
        summarize_component("support_package_safety", "pass" if (root / "scripts" / "create_issue_report.py").exists() else "fail", "Client-safe support package defaults are available."),
    ]

    failures = [item for item in components if item["status"] == "fail"]
    warnings = [item for item in components if item["status"] in {"warn", "unknown"}]
    critical_failures = [
        item
        for item in failures
        if item["name"] in {"handoff_docs", "support_package_capability", "trial_package_validation", "feedback_workflow"}
    ]
    if critical_failures:
        overall = "not_ready"
    elif failures or warnings:
        overall = "needs_attention"
    else:
        overall = "ready"

    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "social_apis": False,
        "direct_posting_apis": False,
        "app_version": version,
        "release_version": release_version,
        "dmg_path": str(dmg_path.relative_to(root)),
        "dmg_exists": dmg_path.exists(),
        "client_workflow_status": status_from(client_workflow, "status", "current_step"),
        "diagnostics_status": status_from(diagnostics, "status"),
        "qa_status": status_from(qa_report, "status"),
        "launch_preflight_status": status_from(launch_preflight, "status", "overall_readiness"),
        "security_status": status_from(security, "status", "overall"),
        "storage_status": status_from(storage, "status", "storage_status"),
        "integrity_status": status_from(integrity, "status", "integrity_status"),
        "handoff_guide_exists": doc_status["CLIENT_HANDOFF_GUIDE.md"],
        "trial_package_exists": trial_package.exists(),
        "trial_package_validation_status": status_from(trial_validation, "status"),
        "feedback_workflow_status": "pass" if (root / "scripts" / "collect_client_feedback.py").exists() else "fail",
        "feedback_summary_exists": bool(feedback_summary),
        "support_package_status": "pass" if (root / "scripts" / "create_issue_report.py").exists() else "fail",
        "support_package_safety_status": "pass" if (root / "scripts" / "create_issue_report.py").exists() else "fail",
        "client_trial_qa_status": status_from(client_trial_qa, "status"),
        "client_language_status": status_from(client_language, "status"),
        "version_alignment_status": "pass" if release_version.lstrip("V") in version or version.startswith(release_version.lstrip("V")) else "warn",
        "support_package_capability_exists": (root / "scripts" / "create_issue_report.py").exists(),
        "docs": doc_status,
        "trial_package_files": trial_file_status,
        "components": components,
        "warnings": warnings,
        "failures": failures,
        "overall_readiness": overall,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a client-facing trial readiness report.")
    parser.add_argument("--root", default=".", help="Project root.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = build_report(root)
    analytics = root / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "trial_readiness_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall_readiness"] != "not_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
