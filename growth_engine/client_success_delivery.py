from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .client_feedback import redact_text
from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


PACKAGE_ROOT = Path("out/client_success_package")
PREVIEW_NAME = "dry_run_preview"
FORBIDDEN_PARTS = {
    "content_inbox",
    "clips",
    "captions",
    "logs",
    "queue",
    "analytics",
    "media_cache",
    "social_exports",
    "approved_posts",
    ".social_token_vault.local",
}
FORBIDDEN_FILENAMES = {
    "runtime_state.db",
    "events.jsonl",
    "audit_log.jsonl",
    "social_connectors.json",
    "live_publish_policy.json",
    "higherkey-local-api-token.txt",
}
FORBIDDEN_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".wav",
    ".mp3",
    ".aif",
    ".aiff",
}
REQUIRED_PACKAGE_DOCS = [
    "CLIENT_SUCCESS_DASHBOARD.md",
    "TRIAL_CLOSEOUT_REPORT.md",
    "CLIENT_SUCCESS_SUMMARY.md",
    "NEXT_ENGAGEMENT_RECOMMENDATION.md",
    "CLIENT_DELIVERY_CHECKLIST.md",
    "CLIENT_HANDOFF_GUIDE.md",
    "CLIENT_QUICK_START.md",
    "TRIAL_LIMITATIONS.md",
    "SUPPORT_NOTE.md",
    "APP_BUILD_INFO.json",
    "CLIENT_SUCCESS_DELIVERY_MANIFEST.json",
    "CLIENT_SUCCESS_DELIVERY_CHECKLIST.md",
    "README_CLIENT_SUCCESS_PACKAGE.md",
]
OPTIONAL_PACKAGE_DOCS = [
    "CLIENT_RELEASE_NOTES.md",
    "CLIENT_UPDATE_MESSAGE.md",
    "CLIENT_TRIAL_SUMMARY.md",
]
PRESENTATION_DOCS = [
    "CLIENT_PRESENTATION_OVERVIEW.md",
    "WHAT_CHANGED.md",
    "WHAT_TO_TRY_NEXT.md",
    "OPERATOR_PRESENTATION_NOTES.md",
]


def _load(config: AppConfig, filename: str, fallback: Any) -> Any:
    return load_json_file(config.analytics_dir / filename, fallback)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _redact(value: Any, config: AppConfig) -> str:
    return redact_text(str(value or ""), config.root)


def _safe_status(data: Any, key: str = "status", default: str = "unknown") -> str:
    if isinstance(data, dict):
        value = str(data.get(key) or "").strip()
        return value or default
    return default


def _items(data: Any, key: str = "items") -> list[dict[str, Any]]:
    values = data.get(key) if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _client_delivery_source(config: AppConfig, name: str) -> Path | None:
    candidates = [
        config.root / "out" / "client_delivery" / name,
        config.root / name,
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _package_id(config: AppConfig, approved: bool) -> str:
    package = _read_json(config.root / "package.json", {})
    version = str(package.get("version") or "unknown").replace("/", "-")
    stamp = utc_now().replace(":", "").replace("-", "").split(".")[0]
    return f"client_success_{version}_{stamp}" if approved else PREVIEW_NAME


def _target_dir(config: AppConfig, approved: bool) -> Path:
    root = config.root / PACKAGE_ROOT
    if not approved:
        return root / PREVIEW_NAME
    base = root / _package_id(config, True)
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = root / f"{base.name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _copy_doc(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _support_note(config: AppConfig) -> str:
    return "\n".join([
        "# Support Note",
        "",
        "This client success package is generated locally for operator review.",
        "Private media, source footage, logs, runtime databases, local connector configs, tokens, secrets, and credentials are excluded by default.",
        "Manual upload remains available. Live posting requires official connector readiness and approval gates.",
    ])


def _readme(config: AppConfig, manifest: dict[str, Any]) -> str:
    return "\n".join([
        "# HigherKey Client Success Package",
        "",
        "HigherKey packages client-ready reports locally. Private media and credentials are excluded by default.",
        "",
        f"Package status: {manifest.get('status')}",
        f"Package path: {_redact(manifest.get('package_path'), config)}",
        "",
        "## Included",
        *[f"- {name}" for name in manifest.get("included", [])],
        "",
        "## Not Included",
        "- Original source media",
        "- content_inbox, raw clips, captions, queue, logs, and runtime databases",
        "- Social connector local config, token vault files, secrets, and credentials",
        "- No package upload or external messaging",
    ])


def _checklist_markdown(checklist: dict[str, Any]) -> str:
    lines = [
        "# Client Success Delivery Checklist",
        "",
        "Review this checklist before sharing the package.",
        "",
    ]
    for item in checklist.get("items", []):
        lines.append(f"- [{item.get('status')}] {item.get('title')} - {item.get('next_action')}")
    return "\n".join(lines)


def _build_info(config: AppConfig) -> dict[str, Any]:
    package = _read_json(config.root / "package.json", {})
    release = _read_json(config.root / "config" / "release.json", {})
    latest_build = _read_json(config.root / "dist" / "latest-build.json", {})
    return {
        "product": "HigherKey Operator OS",
        "package_version": package.get("version"),
        "release_version": release.get("version"),
        "release_name": release.get("release_name"),
        "latest_build": latest_build,
        "local_only": True,
        "manual_upload_available": True,
        "cloud_upload": False,
        "external_messaging": False,
    }


def build_client_success_delivery(config: AppConfig, *, dry_run: bool = True, approve: bool = False) -> dict[str, Any]:
    now = utc_now()
    approved = bool(approve)
    target_dir = _target_dir(config, approved)
    package_root = config.root / PACKAGE_ROOT
    if not _inside(target_dir, package_root):
        raise ValueError("Client success package target escaped package root")

    dashboard = _load(config, "client_success_dashboard.json", {})
    closeout = _load(config, "client_trial_closeout_report.json", {})
    checklist_source = _load(config, "operator_closeout_checklist.json", {})
    recommendation = _load(config, "next_engagement_recommendation.json", {})
    success_summary = _load(config, "client_success_summary.json", {})
    scorecard = _load(config, "client_trial_scorecard.json", {})
    delivery_manifest = _load(config, "client_delivery_manifest.json", {})
    launch = _load(config, "client_launch_readiness.json", {})
    audit = _load(config, "release_candidate_audit.json", {})
    rehearsal = _load(config, "client_rehearsal_report.json", {})

    sources: dict[str, Path | None] = {
        "CLIENT_SUCCESS_DASHBOARD.md": _client_delivery_source(config, "CLIENT_SUCCESS_DASHBOARD.md"),
        "TRIAL_CLOSEOUT_REPORT.md": _client_delivery_source(config, "TRIAL_CLOSEOUT_REPORT.md"),
        "CLIENT_SUCCESS_SUMMARY.md": _client_delivery_source(config, "CLIENT_SUCCESS_SUMMARY.md"),
        "NEXT_ENGAGEMENT_RECOMMENDATION.md": _client_delivery_source(config, "NEXT_ENGAGEMENT_RECOMMENDATION.md"),
        "CLIENT_RELEASE_NOTES.md": _client_delivery_source(config, "CLIENT_RELEASE_NOTES.md"),
        "CLIENT_UPDATE_MESSAGE.md": _client_delivery_source(config, "CLIENT_UPDATE_MESSAGE.md"),
        "CLIENT_TRIAL_SUMMARY.md": _client_delivery_source(config, "CLIENT_TRIAL_SUMMARY.md"),
        "CLIENT_DELIVERY_CHECKLIST.md": _client_delivery_source(config, "CLIENT_DELIVERY_CHECKLIST.md"),
        "CLIENT_HANDOFF_GUIDE.md": _client_delivery_source(config, "CLIENT_HANDOFF_GUIDE.md"),
        "CLIENT_QUICK_START.md": _client_delivery_source(config, "CLIENT_QUICK_START.md"),
        "TRIAL_LIMITATIONS.md": _client_delivery_source(config, "TRIAL_LIMITATIONS.md"),
    }
    included = [name for name, source in sources.items() if source]
    missing_required = [name for name in REQUIRED_PACKAGE_DOCS if name not in included and name not in {"SUPPORT_NOTE.md", "APP_BUILD_INFO.json", "CLIENT_SUCCESS_DELIVERY_MANIFEST.json", "CLIENT_SUCCESS_DELIVERY_CHECKLIST.md", "README_CLIENT_SUCCESS_PACKAGE.md"}]

    checklist = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if not missing_required else "needs_attention",
        "local_only": True,
        "redacted": True,
        "items": [
            {"id": "required_docs", "title": "Required client success docs present", "status": "ready" if not missing_required else "missing", "client_message": "Client success docs are packaged locally.", "path": "out/client_success_package", "next_action": "Build Client Success Dashboard" if missing_required else "Review package"},
            {"id": "build_info", "title": "App build info included", "status": "ready", "client_message": "Package includes build metadata without private runtime data.", "path": "APP_BUILD_INFO.json", "next_action": "Verify Success Package"},
            {"id": "private_media", "title": "Private media excluded", "status": "ready", "client_message": "Source media and raw clips are not included.", "next_action": "Verify Success Package"},
            {"id": "local_auth_files", "title": "Tokens and local auth files excluded", "status": "ready", "client_message": "Local connector configs, token files, and secret files are excluded.", "next_action": "Verify Success Package"},
            {"id": "manual_upload", "title": "Manual upload reminder included", "status": "ready", "client_message": "Manual upload remains available unless official connectors and approval gates are complete.", "next_action": "Review share summary"},
        ],
        "missing_required": missing_required,
    }
    manifest = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if not missing_required else "needs_attention",
        "dry_run": bool(dry_run and not approved),
        "approved": approved,
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "cloud_upload": False,
        "external_messaging": False,
        "package_path": str(target_dir.relative_to(config.root)),
        "included": included + ["SUPPORT_NOTE.md", "APP_BUILD_INFO.json", "CLIENT_SUCCESS_DELIVERY_MANIFEST.json", "CLIENT_SUCCESS_DELIVERY_CHECKLIST.md", "README_CLIENT_SUCCESS_PACKAGE.md"],
        "optional_available": [name for name in OPTIONAL_PACKAGE_DOCS if sources.get(name)],
        "missing_required": missing_required,
        "source_status": {
            "client_success_dashboard": _safe_status(dashboard),
            "trial_closeout": _safe_status(closeout),
            "operator_closeout_checklist": _safe_status(checklist_source),
            "next_engagement": _safe_status(recommendation),
            "client_success_summary": _safe_status(success_summary),
            "scorecard": _safe_status(scorecard, "overall_status"),
            "client_delivery_manifest": _safe_status(delivery_manifest),
            "launch_readiness": _safe_status(launch),
            "release_audit": _safe_status(audit, "overall_readiness"),
            "client_rehearsal": _safe_status(rehearsal),
        },
        "client_message": "HigherKey packages client-ready reports locally. Private media and local auth files are excluded by default.",
    }
    share_summary = {
        "version": 1,
        "updated_at": now,
        "status": manifest["status"],
        "local_only": True,
        "redacted": True,
        "package_path": manifest["package_path"],
        "what_to_send": [
            "README_CLIENT_SUCCESS_PACKAGE.md",
            "CLIENT_SUCCESS_DASHBOARD.md",
            "TRIAL_CLOSEOUT_REPORT.md",
            "CLIENT_SUCCESS_SUMMARY.md",
            "NEXT_ENGAGEMENT_RECOMMENDATION.md",
            "CLIENT_DELIVERY_CHECKLIST.md",
        ],
        "what_not_to_send": [
            "Original source media",
            "Private ingest folders, generated media folders, queue data, logs, analytics dumps, and runtime databases",
            "Token files, secret files, local auth files, social connector local config, and live publish local policy",
        ],
        "next_client_step": _redact(recommendation.get("client_next_step") if isinstance(recommendation, dict) else "Review the closeout package.", config),
        "manual_upload_reminder": "Manual upload remains available. Live posting requires official connector readiness and approval gates.",
    }
    presentation_manifest = {
        "version": 1,
        "updated_at": now,
        "status": "ready",
        "local_only": True,
        "redacted": True,
        "docs": PRESENTATION_DOCS,
        "package_root": str(PACKAGE_ROOT),
    }

    target_dir.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        if source:
            _copy_doc(source, target_dir / name)
    _write_text(target_dir / "SUPPORT_NOTE.md", _support_note(config))
    _write_json(target_dir / "APP_BUILD_INFO.json", _build_info(config))
    _write_json(target_dir / "CLIENT_SUCCESS_DELIVERY_MANIFEST.json", manifest)
    _write_text(target_dir / "CLIENT_SUCCESS_DELIVERY_CHECKLIST.md", _checklist_markdown(checklist))
    _write_text(target_dir / "README_CLIENT_SUCCESS_PACKAGE.md", _readme(config, manifest))

    save_json_file(config.analytics_dir / "client_success_delivery_package.json", manifest)
    save_json_file(config.analytics_dir / "client_success_delivery_checklist.json", checklist)
    save_json_file(config.analytics_dir / "client_success_presentation_manifest.json", presentation_manifest)
    save_json_file(config.analytics_dir / "client_success_share_summary.json", share_summary)
    return {
        "status": manifest["status"],
        "dry_run": manifest["dry_run"],
        "approved": approved,
        "package_path": manifest["package_path"],
        "manifest": manifest,
        "checklist": checklist,
        "presentation_manifest": presentation_manifest,
        "share_summary": share_summary,
    }


def verify_client_success_package(config: AppConfig) -> dict[str, Any]:
    now = utc_now()
    manifest = _load(config, "client_success_delivery_package.json", {})
    package_path = Path(str(manifest.get("package_path") or PACKAGE_ROOT / PREVIEW_NAME))
    package_dir = package_path if package_path.is_absolute() else config.root / package_path
    package_root = config.root / PACKAGE_ROOT
    failures: list[str] = []
    warnings: list[str] = []
    if not _inside(package_dir, package_root):
        failures.append("package_path_outside_client_success_root")
    if not package_dir.exists() or not package_dir.is_dir():
        failures.append("package_missing")

    required = REQUIRED_PACKAGE_DOCS
    missing = [name for name in required if not (package_dir / name).exists()]
    if missing:
        failures.append("required_docs_missing")

    forbidden_hits: list[str] = []
    if package_dir.exists() and _inside(package_dir, package_root):
        for path in package_dir.rglob("*"):
            if path.is_symlink():
                forbidden_hits.append(str(path.relative_to(package_dir)))
                continue
            if not path.is_file():
                continue
            rel = str(path.relative_to(package_dir))
            if not _inside(path, package_dir):
                forbidden_hits.append(rel)
                continue
            lowered_parts = {part.lower() for part in path.parts}
            name = path.name.lower()
            if lowered_parts & FORBIDDEN_PARTS:
                forbidden_hits.append(rel)
            if name in FORBIDDEN_FILENAMES:
                forbidden_hits.append(rel)
            if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
                forbidden_hits.append(rel)
            if "token" in name or "secret" in name or "credential" in name:
                forbidden_hits.append(rel)
            if name.endswith(".json") and name not in {"app_build_info.json", "client_success_delivery_manifest.json"}:
                forbidden_hits.append(rel)
    if forbidden_hits:
        failures.append("forbidden_files_in_package")

    status = "fail" if failures else "pass"
    verification = {
        "version": 1,
        "updated_at": now,
        "status": status,
        "local_only": True,
        "redacted": True,
        "package_path": str(package_dir.relative_to(config.root)) if _inside(package_dir, config.root) else "[outside-project]",
        "required_docs_present": not missing,
        "missing_required": missing,
        "forbidden_hits": sorted(set(forbidden_hits)),
        "failures": failures,
        "warnings": warnings,
        "private_media_included": bool(forbidden_hits),
        "tokens_included": any("token" in hit.lower() or "secret" in hit.lower() or "credential" in hit.lower() for hit in forbidden_hits),
        "cloud_upload": False,
        "external_messaging": False,
    }
    save_json_file(config.analytics_dir / "client_success_package_verification.json", verification)
    return verification


def build_client_success_presentation(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    dashboard = _load(config, "client_success_dashboard.json", {})
    closeout = _load(config, "client_trial_closeout_report.json", {})
    recommendation = _load(config, "next_engagement_recommendation.json", {})
    summary = _load(config, "client_success_summary.json", {})
    package_dir = config.root / PACKAGE_ROOT
    package_dir.mkdir(parents=True, exist_ok=True)
    worked = dashboard.get("what_was_delivered") if isinstance(dashboard, dict) else []
    changed = dashboard.get("what_changed") if isinstance(dashboard, dict) else []
    risks = dashboard.get("remaining_risks") if isinstance(dashboard, dict) else []
    next_steps = dashboard.get("recommended_next_steps") if isinstance(dashboard, dict) else []
    worked = worked if isinstance(worked, list) else []
    changed = changed if isinstance(changed, list) else []
    risks = risks if isinstance(risks, list) else []
    next_steps = next_steps if isinstance(next_steps, list) else []
    docs = {
        "CLIENT_PRESENTATION_OVERVIEW.md": [
            "# Client Presentation Overview",
            "",
            "HigherKey trial materials are prepared locally for operator review before sharing.",
            "",
            f"Overall result: {_redact(summary.get('overall_trial_result') if isinstance(summary, dict) else 'pending', config)}",
            f"Decision: {_redact(recommendation.get('decision') if isinstance(recommendation, dict) else 'pending', config)}",
            "",
            "Manual upload remains available. Live posting requires official connector readiness and approval gates.",
            "Original media remains protected.",
        ],
        "WHAT_CHANGED.md": [
            "# What Changed",
            "",
            *[f"- {_redact(item, config)}" for item in (changed[:8] or ["No verified client-facing changes are listed yet."])],
        ],
        "WHAT_TO_TRY_NEXT.md": [
            "# What To Try Next",
            "",
            *[f"- {_redact(item, config)}" for item in (next_steps[:8] or ["Review the closeout report and run another local rehearsal."])],
        ],
        "OPERATOR_PRESENTATION_NOTES.md": [
            "# Operator Presentation Notes",
            "",
            "Internal notes stay local unless reviewed for sharing.",
            "",
            "## What Worked",
            *[f"- {_redact(item, config)}" for item in (worked[:8] or ["No delivered items listed."])],
            "",
            "## Needs Attention",
            *[f"- {_redact(item, config)}" for item in (risks[:8] or ["No open risks listed."])],
            "",
            f"Closeout status: {_redact(closeout.get('status') if isinstance(closeout, dict) else 'pending', config)}",
        ],
    }
    if not dry_run:
        for name, lines in docs.items():
            _write_text(package_dir / name, "\n".join(lines))
    manifest = {
        "version": 1,
        "updated_at": now,
        "status": "ready",
        "dry_run": dry_run,
        "local_only": True,
        "redacted": True,
        "docs": list(docs.keys()),
        "package_root": str(PACKAGE_ROOT),
        "cloud_upload": False,
        "external_messaging": False,
    }
    save_json_file(config.analytics_dir / "client_success_presentation_manifest.json", manifest)
    return manifest
