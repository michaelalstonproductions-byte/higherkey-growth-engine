#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.marketing_intelligence import write_json

RUNTIME_DIRS = {"analytics", "out", "dist", "queue", "clips", "captions", "content_inbox", "logs"}
PRIVATE_EXTENSIONS = {".mp4", ".mov", ".m4v", ".wav", ".aif", ".aiff"}
FORBIDDEN_PACKAGE_NAMES = {"runtime_state.db", "events.jsonl", "audit_log.jsonl", "higherkey-local-api-token.txt"}
FORBIDDEN_PACKAGE_DIRS = {"content_inbox", "clips", "captions", "logs", "media_cache", "social_exports", "approved_posts"}
SENSITIVE_RE = re.compile(r"(token|secret|password|authorization|bearer\s+[a-z0-9._-]+)", re.IGNORECASE)
ENABLED_API_RE = re.compile(
    r"live_api_enabled\"\s*:\s*true|"
    r"social_posting_allowed\"\s*:\s*true|"
    r"cloud_apis_allowed\"\s*:\s*true|"
    r"direct_posting_apis\"\s*:\s*true|"
    r"\bfetch\s*\(\s*['\"]https?://|"
    r"\baxios\s*\.\s*(get|post|request)\s*\(\s*['\"]https?://",
    re.IGNORECASE,
)

REQUIRED_MODULES = [
    "growth_engine/marketing_intelligence.py",
    "growth_engine/campaign_planner.py",
    "growth_engine/growth_strategy.py",
    "growth_engine/creative_director.py",
    "growth_engine/production_command.py",
    "growth_engine/operator_autopilot.py",
    "growth_engine/autopilot_console.py",
]
REQUIRED_SCRIPTS = [
    "scripts/build_marketing_plan.py",
    "scripts/build_campaign_plan.py",
    "scripts/build_growth_strategy.py",
    "scripts/build_creative_direction.py",
    "scripts/build_production_command.py",
    "scripts/build_operator_autopilot.py",
    "scripts/run_operator_autopilot.py",
    "scripts/autopilot_preflight.py",
    "scripts/build_autopilot_console.py",
]
REQUIRED_CONFIGS = [
    "config/autopilot_policy.json",
    "config/marketing_profile.example.json",
    "config/social_connectors.example.json",
    "config/release.json",
    "config/version_contract.json",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def rel(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def normalize_release(package_version: str) -> str:
    parts = package_version.split(".")
    if len(parts) >= 2:
        return f"V{parts[0]}.{parts[1]}"
    return f"V{package_version}"


def check(name: str, status: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "message": message}
    payload.update(extra)
    return payload


def run(args: list[str], root: Path, timeout: int = 90) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=root, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "args": args,
            "return_code": proc.returncode,
            "stdout_tail": proc.stdout[-1200:],
            "stderr_tail": proc.stderr[-1200:],
            "ok": proc.returncode == 0,
        }
    except Exception as exc:
        return {"args": args, "return_code": None, "stdout_tail": "", "stderr_tail": str(exc), "ok": False}


def tracked_runtime_outputs(root: Path) -> list[str]:
    result = run(["git", "ls-files"], root, timeout=30)
    if not result["ok"]:
        return []
    tracked = []
    for item in str(result["stdout_tail"]).splitlines():
        if item.split("/", 1)[0] in RUNTIME_DIRS:
            tracked.append(item)
    return sorted(tracked)


def scan_tree_for_forbidden(root: Path, folder: Path) -> dict[str, list[str]]:
    forbidden: list[str] = []
    private_media: list[str] = []
    if folder.exists():
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.relative_to(folder).parts)
            if path.name in FORBIDDEN_PACKAGE_NAMES or parts.intersection(FORBIDDEN_PACKAGE_DIRS):
                forbidden.append(rel(path, root))
            if path.suffix.lower() in PRIVATE_EXTENSIONS:
                private_media.append(rel(path, root))
    return {"forbidden": sorted(forbidden), "private_media": sorted(private_media)}


def source_safety_scan(root: Path) -> dict[str, Any]:
    excluded = {".git", "node_modules", "dist", "analytics", "out", "queue", "clips", "captions", "content_inbox", "logs", "__pycache__"}
    risky: list[dict[str, Any]] = []
    token_hits: list[dict[str, Any]] = []
    safe_terms = (
        "no cloud",
        "no social",
        "no live",
        "manual upload",
        "manual import",
        "does not post",
        "no instagram",
        "direct_posting_apis\": false",
        "cloud_apis\": false",
        "social_apis\": false",
        "live_instagram_api\": false",
        "social_posting_allowed\": false",
        "cloud_apis_allowed\": false",
        "token storage",
        "token_storage",
        "tokens are excluded",
        "tokens, or",
        "tokens by default",
        "excludes",
        "excluded",
        "forbidden",
        "not_configured",
        "not configured",
        "sensitive_keys",
        "tokens_included\": false",
        "local token support",
        "token settings",
        "rotate-token",
        "no posting integration",
        "scan_patterns",
        "direct_posting_pattern",
        "re.compile",
        "matched_pattern",
    )
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(root).parts):
            continue
        if path.name == "package-lock.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            scanner_source = rel(path, root) in {"scripts/run_release_candidate_audit.py", "scripts/run_full_qa.py"}
            raw_secret = any(term in lower for term in ("access_token", "client_secret", "refresh_token")) or bool(re.search(r"bearer\s+[a-z0-9._-]{24,}", lower))
            if raw_secret and not scanner_source and not any(term in lower for term in safe_terms):
                token_hits.append({"path": rel(path, root), "line": line_no, "text": line.strip()[:220]})
            if ENABLED_API_RE.search(line) and not any(term in lower for term in safe_terms) and "localhost" not in lower and "127.0.0.1" not in lower:
                risky.append({"path": rel(path, root), "line": line_no, "text": line.strip()[:220]})
    return {"risky_hits": risky, "token_hits": token_hits}


def packaged_required_paths(root: Path) -> dict[str, Any]:
    resources = root / "dist" / "mac-arm64" / "HigherKey Operator OS.app" / "Contents" / "Resources"
    required = [resources / "app.asar"]
    required += [resources / "app-assets" / item for item in REQUIRED_MODULES + REQUIRED_SCRIPTS + REQUIRED_CONFIGS]
    missing = [rel(path, root) for path in required if not path.exists()]
    forbidden = [rel(resources / "app-assets" / item, root) for item in RUNTIME_DIRS if (resources / "app-assets" / item).exists()]
    return {"app_bundle_exists": resources.exists(), "missing": missing, "forbidden_runtime_dirs": forbidden}


def version_alignment(root: Path) -> dict[str, Any]:
    package = load_json(root / "package.json", {})
    lock = load_json(root / "package-lock.json", {})
    release = load_json(root / "config" / "release.json", {})
    contract = load_json(root / "config" / "version_contract.json", {})
    package_version = str(package.get("version") if isinstance(package, dict) else "")
    expected_release = normalize_release(package_version)
    root_lock = lock.get("packages", {}).get("", {}) if isinstance(lock, dict) and isinstance(lock.get("packages"), dict) else {}
    has_path = False
    if isinstance(contract, dict):
        has_path = any(item.get("from") == "V5.9" and item.get("to") == "V6.0" for item in contract.get("supported_upgrade_paths", []))
    return {
        "package_version": package_version,
        "package_lock_version": str(lock.get("version", "")) if isinstance(lock, dict) else "",
        "package_lock_root_version": str(root_lock.get("version", "")),
        "release_version": str(release.get("version", "")) if isinstance(release, dict) else "",
        "release_name": str(release.get("release_name", "")) if isinstance(release, dict) else "",
        "contract_app_version": str(contract.get("app_version", "")) if isinstance(contract, dict) else "",
        "contract_release_version": str(contract.get("release_version", "")) if isinstance(contract, dict) else "",
        "has_v59_to_v60_path": has_path,
        "aligned": package_version == "6.0.0"
        and str(root_lock.get("version", "")) == package_version
        and str(lock.get("version", "")) == package_version
        and str(release.get("version", "")) == expected_release
        and str(release.get("release_name", "")) == "Release Candidate"
        and str(contract.get("app_version", "")) == package_version
        and str(contract.get("release_version", "")) == expected_release
        and has_path,
    }


def build_local_outputs(root: Path) -> dict[str, Any]:
    scripts = [
        ["python3", "scripts/build_production_command.py"],
        ["python3", "scripts/build_operator_autopilot.py"],
        ["python3", "scripts/autopilot_preflight.py"],
        ["python3", "scripts/build_autopilot_console.py"],
    ]
    results = [run(args, root, timeout=120) for args in scripts]
    return {"ok": all(item["ok"] for item in results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey release-candidate safety and packaging audit.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON only.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    analytics = root / "analytics"
    package = load_json(root / "package.json", {})
    package_version = str(package.get("version") if isinstance(package, dict) else "unknown")
    dmg_path = root / "dist" / f"HigherKey Operator OS-{package_version}-arm64.dmg"
    latest_build = load_json(root / "dist" / "latest-build.json", {})
    source_safety = source_safety_scan(root)
    trial_scan = scan_tree_for_forbidden(root, root / "out" / "trial_release")
    handoff_scan = scan_tree_for_forbidden(root, root / "out" / "client_handoff")
    support_scan = scan_tree_for_forbidden(root, root / "out" / "client_issue_report")
    packaged = packaged_required_paths(root)
    version = version_alignment(root)
    local_builds = build_local_outputs(root)
    tracked_runtime = tracked_runtime_outputs(root)
    docs_text = "\n".join(
        (root / name).read_text(encoding="utf-8") if (root / name).exists() else ""
        for name in ["README.md", "CLIENT_QUICK_START.md", "CLIENT_HANDOFF_GUIDE.md", "TRIAL_DELIVERY_CHECKLIST.md", "CLIENT_TRIAL_QA_SUMMARY.md"]
    ).lower()
    checks = [
        check("version_metadata_alignment", "pass" if version["aligned"] else "fail", "V6.0 package, release, lockfile, and upgrade contract align.", **version),
        check("latest_build_manifest", "pass" if latest_build else "needs_attention", "dist/latest-build.json exists after a desktop build.", exists=bool(latest_build)),
        check("dmg_exists", "pass" if dmg_path.exists() else "needs_attention", "Expected V6.0 DMG exists after unsigned packaging.", path=rel(dmg_path, root), exists=dmg_path.exists()),
        check("app_bundle_exists", "pass" if packaged["app_bundle_exists"] else "needs_attention", "Unpacked app bundle exists after dist:dir.", exists=packaged["app_bundle_exists"]),
        check("packaged_required_files", "pass" if not packaged["missing"] else "needs_attention", "Packaged app contains required V6 modules, scripts, and configs.", missing=packaged["missing"]),
        check("packaged_runtime_exclusions", "pass" if not packaged["forbidden_runtime_dirs"] else "fail", "Packaged resources exclude runtime output folders.", forbidden=packaged["forbidden_runtime_dirs"]),
        check("tracked_runtime_outputs", "pass" if not tracked_runtime else "fail", "Generated runtime outputs are not tracked in git.", tracked=tracked_runtime),
        check("trial_package_safety", "pass" if not trial_scan["forbidden"] and not trial_scan["private_media"] else "fail", "Trial package excludes private media and runtime folders.", **trial_scan),
        check("client_handoff_safety", "pass" if not handoff_scan["forbidden"] and not handoff_scan["private_media"] else "fail", "Client handoff excludes private media and runtime folders.", **handoff_scan),
        check("support_package_safety", "pass" if not support_scan["forbidden"] and not support_scan["private_media"] else "fail", "Support package excludes private media, runtime DB, logs, and media folders by default.", **support_scan),
        check("source_secret_scan", "pass" if not source_safety["token_hits"] else "fail", "No raw tokens or secrets detected in source.", hits=source_safety["token_hits"][:20]),
        check("cloud_social_api_scan", "pass" if not source_safety["risky_hits"] else "fail", "No cloud, live Instagram, or social posting API calls detected.", risky_hits=source_safety["risky_hits"][:20]),
        check("manual_upload_language", "pass" if "manual upload" in docs_text and "no social posting" in docs_text else "fail", "Docs include manual upload and no social posting language."),
        check("client_quick_start", "pass" if (root / "CLIENT_QUICK_START.md").exists() else "fail", "Client quick start exists."),
        check("readme_release_notes", "pass" if "v6.0 release candidate" in docs_text else "fail", "README includes V6.0 release candidate notes."),
        check("support_workflow", "pass" if (root / "scripts" / "create_issue_report.py").exists() else "fail", "Support package script exists."),
        check("trial_workflow", "pass" if (root / "scripts" / "package_trial_release.py").exists() else "fail", "Trial package script exists."),
        check("local_command_outputs", "pass" if local_builds["ok"] else "fail", "Production command and Autopilot console build locally.", results=local_builds["results"]),
    ]
    failures = [item for item in checks if item["status"] == "fail"]
    attention = [item for item in checks if item["status"] == "needs_attention"]
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis": False,
        "live_instagram_api": False,
        "social_posting_apis": False,
        "overall_readiness": "not_ready" if failures else ("needs_attention" if attention else "ready"),
        "checks": checks,
        "required_packaged_files": {
            "modules": REQUIRED_MODULES,
            "scripts": REQUIRED_SCRIPTS,
            "configs": REQUIRED_CONFIGS,
        },
    }
    write_json(analytics / "release_candidate_audit.json", report)
    print(json.dumps(report, indent=None if args.json else 2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
