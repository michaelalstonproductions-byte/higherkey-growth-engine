from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .client_feedback import redact_text
from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


PATCH_STATUSES = {
    "planned",
    "in_progress",
    "fixed",
    "needs_verification",
    "verified",
    "ready_for_release",
    "deferred",
    "closed",
}
RELEASE_READY_STATUSES = {"verified", "ready_for_release", "closed"}
PRIORITY_BY_SEVERITY = {"blocker": 1, "high": 2, "medium": 3, "low": 4}


def _load(path: Path, fallback: Any) -> Any:
    return load_json_file(path, fallback)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_status(value: str | None) -> str:
    text = (value or "planned").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in PATCH_STATUSES else "planned"


def _items_from(value: Any, key: str = "items") -> list[dict[str, Any]]:
    items = value.get(key) if isinstance(value, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _redact(value: Any, config: AppConfig) -> str:
    return redact_text(str(value or ""), config.root)


def _existing_statuses(config: AppConfig) -> dict[str, dict[str, str]]:
    board = _load(config.analytics_dir / "patch_execution_board.json", {})
    status = {"patch": {}, "triage": {}, "issue": {}}
    for item in _items_from(board):
        normalized = _normalize_status(str(item.get("status") or ""))
        if item.get("patch_id"):
            status["patch"][str(item["patch_id"])] = normalized
        if item.get("triage_id"):
            status["triage"][str(item["triage_id"])] = normalized
        if item.get("issue_id"):
            status["issue"][str(item["issue_id"])] = normalized
    return status


def _verification_steps(item: dict[str, Any]) -> list[str]:
    category = str(item.get("category") or "other")
    base = [
        "Reproduce the affected client workflow locally.",
        "Run the focused script or UI action for the affected page.",
        "Run dashboard JS syntax, client rehearsal, release audit, and qa:full before release.",
    ]
    if category in {"export_issue", "delivery_issue"}:
        base.insert(1, "Verify generated packages exclude originals, tokens, logs, and local connector config.")
    if category in {"social_connector_issue"}:
        base.insert(1, "Verify manual upload remains available and live posting gates still require approval.")
    if category in {"editor_issue"}:
        base.insert(1, "Verify original media protection, approval receipts, and edited export containment.")
    return base


def _source_patch_items(config: AppConfig) -> list[dict[str, Any]]:
    patch_plan = _load(config.analytics_dir / "client_patch_plan.json", {})
    triage = _load(config.analytics_dir / "feedback_triage_report.json", {})
    issues = _load(config.analytics_dir / "client_issue_queue.json", {})
    source = _items_from(patch_plan) or _items_from(triage)
    if source:
        return source
    fallback = []
    for issue in _items_from(issues, "issues"):
        fallback.append({
            "triage_id": "",
            "issue_ids": [issue.get("issue_id")] if issue.get("issue_id") else [],
            "feedback_ids": issue.get("feedback_ids") if isinstance(issue.get("feedback_ids"), list) else [],
            "title": issue.get("title") or "Trial issue",
            "category": issue.get("category") or "other",
            "severity": issue.get("severity") or "medium",
            "priority": PRIORITY_BY_SEVERITY.get(str(issue.get("severity") or "medium"), 4),
            "affected_page": issue.get("related_page") or "Trial Ops",
            "affected_action": issue.get("related_action") or issue.get("title") or "Review locally",
            "recommended_fix": issue.get("next_action") or "Review locally and patch the affected workflow.",
            "verification_needed": "Run focused verification, client rehearsal, release audit, and qa:full.",
            "status": issue.get("status") or "planned",
        })
    return fallback


def build_patch_execution_board(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    status_overrides = _existing_statuses(config)
    items: list[dict[str, Any]] = []
    for source in _source_patch_items(config):
        triage_id = _redact(source.get("triage_id"), config)
        issue_ids = [str(item) for item in source.get("issue_ids", []) if item] if isinstance(source.get("issue_ids"), list) else []
        issue_id = issue_ids[0] if issue_ids else _redact(source.get("issue_id"), config)
        feedback_ids = [str(item) for item in source.get("feedback_ids", []) if item] if isinstance(source.get("feedback_ids"), list) else []
        category = _redact(source.get("category") or "other", config) or "other"
        severity = _redact(source.get("severity") or "medium", config) or "medium"
        patch_id = "patch_" + _stable_id(triage_id, issue_id, category, ",".join(feedback_ids))
        status = (
            status_overrides["patch"].get(patch_id)
            or (status_overrides["triage"].get(triage_id) if triage_id else None)
            or (status_overrides["issue"].get(issue_id) if issue_id else None)
            or _normalize_status(str(source.get("status") or "planned"))
        )
        if status in {"new", "triaged"}:
            status = "planned"
        item = {
            "patch_id": patch_id,
            "triage_id": triage_id,
            "issue_id": issue_id,
            "feedback_ids": feedback_ids,
            "title": _redact(source.get("title") or f"{severity.title()} {category.replace('_', ' ')} fix", config),
            "category": category,
            "severity": severity,
            "priority": int(source.get("priority") or PRIORITY_BY_SEVERITY.get(severity, 4)),
            "affected_page": _redact(source.get("affected_page") or "Trial Ops", config),
            "affected_action": _redact(source.get("affected_action") or "Review locally", config),
            "recommended_fix": _redact(source.get("recommended_fix") or "Patch the affected workflow and rerun local verification.", config),
            "verification_needed": _redact(source.get("verification_needed") or "Focused local verification is required.", config),
            "verification_steps": _verification_steps(source),
            "status": _normalize_status(status),
            "operator_notes": _redact(source.get("operator_note") or "", config),
            "client_note": _redact(source.get("client_response") or "We are verifying this trial item locally before sending a client update.", config),
            "created_at": source.get("created_at") or now,
            "updated_at": now,
        }
        items.append(item)
    items.sort(key=lambda item: (item.get("priority", 9), item.get("category", ""), item.get("patch_id", "")))
    counts = {status: len([item for item in items if item.get("status") == status]) for status in sorted(PATCH_STATUSES)}
    board = {
        "version": 1,
        "updated_at": now,
        "status": "needs_attention" if counts.get("planned") or counts.get("in_progress") or counts.get("needs_verification") else "ready",
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "items": items,
        "summary": {
            "total": len(items),
            "planned": counts.get("planned", 0),
            "in_progress": counts.get("in_progress", 0),
            "fixed": counts.get("fixed", 0),
            "needs_verification": counts.get("needs_verification", 0),
            "verified": counts.get("verified", 0),
            "ready_for_release": counts.get("ready_for_release", 0),
            "deferred": counts.get("deferred", 0),
        },
    }
    verification = {
        "version": 1,
        "updated_at": now,
        "status": board["status"],
        "local_only": True,
        "redacted": True,
        "items": [
            {
                "patch_id": item["patch_id"],
                "title": item["title"],
                "status": item["status"],
                "verification_steps": item["verification_steps"],
                "verification_needed": item["verification_needed"],
            }
            for item in items
        ],
    }
    client_status = {
        "version": 1,
        "updated_at": now,
        "status": board["status"],
        "local_only": True,
        "redacted": True,
        "client_message": "Patch work is tracked locally. Client release notes are drafts until reviewed by the operator.",
        "summary": board["summary"],
        "items": [
            {
                "patch_id": item["patch_id"],
                "title": item["title"],
                "status": item["status"],
                "client_note": item["client_note"],
            }
            for item in items
        ],
    }
    result = {
        "status": board["status"],
        "dry_run": dry_run,
        "patch_execution_board": board,
        "patch_verification_plan": verification,
        "client_patch_status": client_status,
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "patch_execution_board.json", board)
        save_json_file(config.analytics_dir / "patch_verification_plan.json", verification)
        save_json_file(config.analytics_dir / "client_patch_status.json", client_status)
        _write_execution_docs(config, board, verification)
    return result


def _write_execution_docs(config: AppConfig, board: dict[str, Any], verification: dict[str, Any]) -> None:
    out = config.root / "out" / "client_delivery"
    lines = [
        "# Patch Execution Board",
        "",
        "Patch work stays local. Status changes are operator-controlled and are not sent externally.",
        "",
        f"Status: {board.get('status')}",
        "",
    ]
    for item in board.get("items", []):
        lines.extend([
            f"## {item.get('title')}",
            f"- Status: {item.get('status')}",
            f"- Severity: {item.get('severity')}",
            f"- Page: {item.get('affected_page')}",
            f"- Action: {item.get('affected_action')}",
            f"- Recommended fix: {item.get('recommended_fix')}",
            "",
        ])
    if not board.get("items"):
        lines.append("No patch execution tasks are currently queued.")
    _write_text(out / "PATCH_EXECUTION_BOARD.md", "\n".join(lines))

    checklist = [
        "# Patch Verification Checklist",
        "",
        "Run this checklist locally before preparing client release notes.",
        "",
    ]
    for item in verification.get("items", []):
        checklist.extend([f"## {item.get('title')}", f"- Status: {item.get('status')}"])
        for step in item.get("verification_steps", []) if isinstance(item.get("verification_steps"), list) else []:
            checklist.append(f"- [ ] {step}")
        checklist.append("")
    if not verification.get("items"):
        checklist.append("No patch verification items are currently queued.")
    _write_text(out / "PATCH_VERIFICATION_CHECKLIST.md", "\n".join(checklist))


def update_patch_execution_status(
    config: AppConfig,
    *,
    patch_id: str = "",
    triage_id: str = "",
    issue_id: str = "",
    status: str = "planned",
    note: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_status(status)
    if not patch_id and not triage_id and not issue_id:
        board = _load(config.analytics_dir / "patch_execution_board.json", {})
        first = next((item for item in _items_from(board) if isinstance(item, dict)), None)
        if first:
            patch_id = str(first.get("patch_id") or "")
    now = utc_now()
    note = _redact(note or "Patch status updated locally.", config)
    board = _load(config.analytics_dir / "patch_execution_board.json", {})
    if not isinstance(board, dict) or not isinstance(board.get("items"), list):
        build_result = build_patch_execution_board(config, dry_run=True)
        board = build_result["patch_execution_board"]
    matched = False
    for item in board.get("items", []):
        if not isinstance(item, dict):
            continue
        if (
            (patch_id and item.get("patch_id") == patch_id)
            or (triage_id and item.get("triage_id") == triage_id)
            or (issue_id and item.get("issue_id") == issue_id)
        ):
            item["status"] = normalized
            item["operator_notes"] = note
            item["updated_at"] = now
            matched = True
    if not matched:
        board.setdefault("items", []).append({
            "patch_id": patch_id,
            "triage_id": triage_id,
            "issue_id": issue_id,
            "feedback_ids": [],
            "title": "Local patch status update",
            "category": "other",
            "severity": "medium",
            "priority": 4,
            "affected_page": "Trial Ops",
            "affected_action": "Patch status",
            "recommended_fix": "Review the local patch status update.",
            "verification_needed": "Run local verification before release.",
            "verification_steps": ["Run focused local verification.", "Run qa:full before release."],
            "status": normalized,
            "operator_notes": note,
            "client_note": "Patch status was updated locally and will be reviewed before sending.",
            "created_at": now,
            "updated_at": now,
        })
    board["updated_at"] = now

    client_status = {
        "version": 1,
        "updated_at": now,
        "status": board.get("status") or "needs_attention",
        "local_only": True,
        "redacted": True,
        "client_message": "Patch status is tracked locally and reviewed before client updates are sent.",
        "items": [
            {
                "patch_id": item.get("patch_id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "client_note": item.get("client_note"),
            }
            for item in _items_from(board)
        ],
    }
    response = _load(config.analytics_dir / "client_response_notes.json", {})
    if not isinstance(response, dict):
        response = {"version": 1, "updated_at": now, "status": "draft", "local_only": True, "redacted": True, "notes": []}
    notes = response.get("notes") if isinstance(response.get("notes"), list) else []
    notes.append({
        "patch_id": patch_id,
        "triage_id": triage_id,
        "issue_id": issue_id,
        "status": normalized,
        "client_response": "Patch status was updated locally. The operator will review before sending any client message.",
        "operator_note": note,
        "updated_at": now,
    })
    response["notes"] = notes
    response["updated_at"] = now
    if not dry_run:
        save_json_file(config.analytics_dir / "patch_execution_board.json", board)
        save_json_file(config.analytics_dir / "client_patch_status.json", client_status)
        save_json_file(config.analytics_dir / "client_response_notes.json", response)
    return {
        "status": "pass",
        "dry_run": dry_run,
        "patch_id": patch_id,
        "triage_id": triage_id,
        "issue_id": issue_id,
        "new_status": normalized,
        "patch_execution_board": "analytics/patch_execution_board.json",
        "client_patch_status": "analytics/client_patch_status.json",
    }


def build_client_release_notes(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    board = _load(config.analytics_dir / "patch_execution_board.json", {})
    if not _items_from(board):
        board = build_patch_execution_board(config, dry_run=True)["patch_execution_board"]
    items = _items_from(board)
    client_items = [item for item in items if item.get("status") in RELEASE_READY_STATUSES]
    internal_items = [item for item in items if item.get("status") not in RELEASE_READY_STATUSES]
    patch_notes = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if client_items else "draft",
        "local_only": True,
        "redacted": True,
        "items": items,
    }
    client_notes = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if client_items else "draft",
        "local_only": True,
        "redacted": True,
        "client_message": "These release notes are generated locally for operator review before sending.",
        "items": [
            {
                "patch_id": item.get("patch_id"),
                "title": item.get("title"),
                "category": item.get("category"),
                "status": item.get("status"),
                "client_note": item.get("client_note"),
            }
            for item in client_items
        ],
        "internal_only": [
            {
                "patch_id": item.get("patch_id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "operator_notes": item.get("operator_notes"),
            }
            for item in internal_items
        ],
    }
    result = {
        "status": client_notes["status"],
        "dry_run": dry_run,
        "patch_release_notes": patch_notes,
        "client_release_notes": client_notes,
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "patch_release_notes.json", patch_notes)
        save_json_file(config.analytics_dir / "client_release_notes.json", client_notes)
        _write_release_docs(config, client_notes, internal_items)
    return result


def _write_release_docs(config: AppConfig, client_notes: dict[str, Any], internal_items: list[dict[str, Any]]) -> None:
    out = config.root / "out" / "client_delivery"
    release_lines = [
        "# Client Release Notes",
        "",
        "Draft release notes. Review before sending to a client.",
        "",
    ]
    for item in client_notes.get("items", []):
        release_lines.extend([
            f"## {item.get('title')}",
            f"- Status: {item.get('status')}",
            f"- Category: {item.get('category')}",
            "",
            str(item.get("client_note") or "Verified locally for client release."),
            "",
        ])
    if not client_notes.get("items"):
        release_lines.append("No verified patch items are ready for client release notes yet.")
    _write_text(out / "CLIENT_RELEASE_NOTES.md", "\n".join(release_lines))

    update_lines = [
        "# Client Update Message",
        "",
        "Draft only. No message is sent automatically.",
        "",
        "Hi - we prepared a local update based on trial feedback. The notes below are ready for operator review before sending.",
        "",
    ]
    for item in client_notes.get("items", []):
        update_lines.append(f"- {item.get('title')}: {item.get('client_note')}")
    if not client_notes.get("items"):
        update_lines.append("- No verified patch updates are ready to send yet.")
    _write_text(out / "CLIENT_UPDATE_MESSAGE.md", "\n".join(update_lines))

    internal_lines = [
        "# Internal Patch Notes",
        "",
        "Internal-only local patch status. Do not send without operator review.",
        "",
    ]
    for item in internal_items:
        internal_lines.extend([
            f"## {item.get('title')}",
            f"- Status: {item.get('status')}",
            f"- Operator notes: {item.get('operator_notes') or 'None'}",
            "",
        ])
    if not internal_items:
        internal_lines.append("No internal-only patch items remain.")
    _write_text(out / "INTERNAL_PATCH_NOTES.md", "\n".join(internal_lines))
