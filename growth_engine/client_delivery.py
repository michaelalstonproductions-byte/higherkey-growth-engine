from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


PRIVATE_DIRS = {"content_inbox", "clips", "logs", "analytics", "queue"}
CONDITIONALLY_SAFE_DIRS = {"captions"}
FORBIDDEN_FILENAMES = {
    "runtime_state.db",
    "events.jsonl",
    "audit_log.jsonl",
    "social_connectors.json",
    ".social_token_vault.local",
    "live_publish_policy.json",
}
SECRET_RE = re.compile(r"(token|secret|credential|password|bearer|authorization)", re.IGNORECASE)
DMG_RE = re.compile(r"HigherKey Operator OS-\d+\.\d+\.\d+-arm64\.dmg$")


def _load(path: Path, fallback: Any) -> Any:
    return load_json_file(path, fallback)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _package_json(config: AppConfig) -> dict[str, Any]:
    return _load(config.root / "package.json", {})


def _release_json(config: AppConfig) -> dict[str, Any]:
    return _load(config.root / "config" / "release.json", {})


def _latest_dmg(config: AppConfig, package_version: str) -> Path | None:
    expected = config.root / "dist" / f"HigherKey Operator OS-{package_version}-arm64.dmg"
    if expected.exists():
        return expected
    candidates = sorted((config.root / "dist").glob("HigherKey Operator OS-*-arm64.dmg"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return candidates[0] if candidates else None


def _scan_package(folder: Path, root: Path) -> dict[str, Any]:
    forbidden: list[str] = []
    private_media: list[str] = []
    if folder.exists():
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = set(path.relative_to(folder).parts)
            if rel_parts & PRIVATE_DIRS or path.name in FORBIDDEN_FILENAMES or SECRET_RE.search(path.name):
                forbidden.append(relative_path(path, root))
            if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".wav", ".aif", ".aiff"}:
                private_media.append(relative_path(path, root))
    return {"exists": folder.exists(), "forbidden": sorted(forbidden), "private_media": sorted(private_media)}


def _check(item_id: str, title: str, status: str, message: str, *, path: Path | None = None, next_action: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": item_id,
        "title": title,
        "status": status,
        "client_message": message,
        "next_action": next_action,
    }
    if path is not None:
        item["path"] = str(path)
    if details:
        item["technical_details"] = details
    return item


def build_client_delivery_manifest(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    package = _package_json(config)
    release = _release_json(config)
    package_version = str(package.get("version") or "unknown")
    release_version = str(release.get("version") or "unknown")
    latest_build = _load(config.root / "dist" / "latest-build.json", {})
    release_audit = _load(config.analytics_dir / "release_candidate_audit.json", {})
    rehearsal = _load(config.analytics_dir / "client_rehearsal_report.json", {})
    client_state = _load(config.analytics_dir / "client_state.json", {})
    social = _load(config.analytics_dir / "client_social_connection_status.json", {})
    live = _load(config.analytics_dir / "client_live_publish_readiness.json", {})
    delivery_state = _load(config.analytics_dir / "client_editing_delivery_state.json", {})
    edited_verify = _load(config.analytics_dir / "edited_delivery_package_verification.json", {})

    dmg = _latest_dmg(config, package_version)
    handoff = _scan_package(config.root / "out" / "client_handoff", config.root)
    trial = _scan_package(config.root / "out" / "trial_release", config.root)
    support = _scan_package(config.root / "out" / "client_issue_report", config.root)
    edited_delivery = _scan_package(config.root / "out" / "client_delivery" / "edited_assets", config.root)

    audit_ready = release_audit.get("overall_readiness") == "ready"
    rehearsal_ok = rehearsal.get("status") in {"pass", "ready"}
    edited_verify_ok = edited_verify.get("status") in {None, "pass"} and edited_verify.get("original_media_included") is not True
    handoff_safe = handoff["exists"] and not handoff["forbidden"] and not handoff["private_media"]
    trial_safe = trial["exists"] and not trial["forbidden"] and not trial["private_media"]
    support_safe = not support["forbidden"] and not support["private_media"]

    checklist = [
        _check("app_build", "App Build", "ready" if package_version != "unknown" and release_version != "unknown" else "missing", f"HigherKey is reporting {package_version} / {release_version}.", next_action="Run Launch Audit", details={"package_version": package_version, "release_version": release_version, "latest_build": latest_build}),
        _check("current_dmg", "Current DMG", "ready" if dmg and dmg.exists() and DMG_RE.match(dmg.name) else "missing", "The current DMG is available for handoff." if dmg else "No current DMG was found.", path=Path(relative_path(dmg, config.root)) if dmg else None, next_action="Run dist:unsigned"),
        _check("client_handoff", "Client Handoff", "ready" if handoff_safe else ("missing" if not handoff["exists"] else "needs_attention"), "Client handoff package is safe to share." if handoff_safe else "Build or review the client handoff package before sending.", path=Path("out/client_handoff"), next_action="Build Client Handoff", details=handoff),
        _check("trial_package", "Trial Package", "ready" if trial_safe else ("missing" if not trial["exists"] else "needs_attention"), "Trial package is safe to share." if trial_safe else "Build or review the trial package before sending.", path=Path("out/trial_release"), next_action="Build Trial Package", details=trial),
        _check("support_package", "Support Package", "ready" if support_safe else "needs_attention", "Support package defaults are client-safe.", path=Path("out/client_issue_report"), next_action="Build Support Package", details=support),
        _check("release_audit", "Launch Audit", "ready" if audit_ready else "needs_attention", "Release audit is ready." if audit_ready else "Run the launch audit and resolve any failures.", next_action="Run Launch Audit", details={"overall_readiness": release_audit.get("overall_readiness")}),
        _check("client_rehearsal", "Client Rehearsal", "ready" if rehearsal_ok else "needs_attention", "Client rehearsal passed." if rehearsal_ok else "Run the client rehearsal before handoff.", next_action="Run Client Rehearsal", details={"status": rehearsal.get("status")}),
        _check("social_safety", "Social Safety", "ready", "Manual upload remains available. Live posting requires official account connection and approval.", next_action="Check Social Connectors", details={"connection_status": social.get("status"), "live_status": live.get("status")}),
        _check("editing_safety", "Editing Safety", "ready" if delivery_state.get("summary", {}).get("originals_protected", True) is not False else "needs_attention", "Edited assets preserve original media.", next_action="Verify Edited Delivery", details=delivery_state.get("summary", {})),
        _check("delivery_package", "Delivery Package", "ready" if edited_verify_ok and edited_delivery["exists"] else ("skipped" if not edited_delivery["exists"] else "needs_attention"), "Edited delivery packages exclude originals by default." if edited_verify_ok and edited_delivery["exists"] else ("No edited delivery package is present; skip this unless approved edited assets are being delivered." if not edited_delivery["exists"] else "Verify edited delivery package before sending."), path=Path("out/client_delivery/edited_assets"), next_action="Verify Edited Delivery", details={"verification": edited_verify, "package_scan": edited_delivery}),
        _check("manual_upload", "Manual Upload Reminder", "ready", "HigherKey prepares local assets and packages. Manual upload remains available.", next_action="Open Social Exports"),
        _check("known_warnings", "Known Warnings", "ready", "Unsigned local DMGs may require macOS approval when opened.", next_action="Share limitations note"),
    ]
    status_order = {"missing": 2, "needs_attention": 1, "skipped": 0, "ready": 0}
    overall = "ready" if not any(status_order.get(item["status"], 1) > 0 for item in checklist) else "needs_attention"

    manifest = {
        "version": 1,
        "updated_at": utc_now(),
        "product": "HigherKey Operator OS",
        "package_version": package_version,
        "release_version": release_version,
        "release_name": release.get("release_name"),
        "status": overall,
        "local_only": True,
        "manual_upload_available": True,
        "cloud_apis": False,
        "social_posting_apis": False,
        "latest_dmg": relative_path(dmg, config.root) if dmg else None,
        "active_project": client_state.get("project_root") or str(config.root),
        "checklist": checklist,
        "send_to_client": [
            "Latest DMG pointer or DMG file when intentionally included.",
            "CLIENT_QUICK_START.md",
            "CLIENT_HANDOFF_GUIDE.md",
            "CLIENT_DELIVERY_CHECKLIST.md",
            "Client handoff or trial package from out/.",
            "Approved edited delivery package when available.",
        ],
        "do_not_send": [
            "content_inbox/",
            "clips/",
            "logs/",
            "analytics/runtime_state.db",
            "config/social_connectors.json",
            "config/.social_token_vault.local",
            "config/live_publish_policy.json",
            "tokens, secrets, credentials, or original private source media",
        ],
    }
    readiness = {
        "version": 1,
        "updated_at": manifest["updated_at"],
        "status": overall,
        "ready_count": len([item for item in checklist if item["status"] == "ready"]),
        "needs_attention_count": len([item for item in checklist if item["status"] == "needs_attention"]),
        "missing_count": len([item for item in checklist if item["status"] == "missing"]),
        "manual_upload_available": True,
        "original_media_excluded_by_default": True,
    }
    checklist_payload = {"version": 1, "updated_at": manifest["updated_at"], "status": overall, "items": checklist}
    handoff_status = {"version": 1, "updated_at": manifest["updated_at"], "status": "ready" if handoff_safe else "needs_attention", **handoff}
    support_status = {"version": 1, "updated_at": manifest["updated_at"], "status": "ready" if support_safe else "needs_attention", **support}

    if not dry_run:
        save_json_file(config.analytics_dir / "client_delivery_manifest.json", manifest)
        save_json_file(config.analytics_dir / "client_launch_readiness.json", readiness)
        save_json_file(config.analytics_dir / "client_delivery_checklist.json", checklist_payload)
        save_json_file(config.analytics_dir / "client_handoff_status.json", handoff_status)
        save_json_file(config.analytics_dir / "client_support_status.json", support_status)
        _write_delivery_docs(config, manifest, checklist)
    return {
        "manifest": manifest,
        "readiness": readiness,
        "checklist": checklist_payload,
        "handoff_status": handoff_status,
        "support_status": support_status,
    }


def _write_delivery_docs(config: AppConfig, manifest: dict[str, Any], checklist: list[dict[str, Any]]) -> None:
    out = config.root / "out" / "client_delivery"
    lines = [
        "# HigherKey Client Delivery",
        "",
        f"Version: {manifest.get('package_version')} / {manifest.get('release_version')}",
        "",
        "HigherKey prepares local assets and packages. Manual upload remains available. Live posting requires official account connection and approval.",
        "",
        "## Send To Client",
        *[f"- {item}" for item in manifest.get("send_to_client", [])],
        "",
        "## Do Not Send",
        *[f"- {item}" for item in manifest.get("do_not_send", [])],
        "",
    ]
    _write_text(out / "CLIENT_DELIVERY_README.md", "\n".join(lines))
    checklist_lines = [
        "# Client Delivery Checklist",
        "",
        *[f"- [{ 'x' if item.get('status') == 'ready' else ' ' }] {item.get('title')}: {item.get('client_message')} Next: {item.get('next_action')}" for item in checklist],
        "",
    ]
    _write_text(out / "CLIENT_DELIVERY_CHECKLIST.md", "\n".join(checklist_lines))
