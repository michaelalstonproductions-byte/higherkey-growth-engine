from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .client_feedback import redact_text
from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


TRIAGE_STATUSES = {
    "new",
    "triaged",
    "planned",
    "in_progress",
    "fixed",
    "needs_client_info",
    "deferred",
    "closed",
}
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
    text = (value or "triaged").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in TRIAGE_STATUSES else "triaged"


def _feedback_items(config: AppConfig) -> list[dict[str, Any]]:
    inbox = _load(config.analytics_dir / "client_feedback_inbox.json", {})
    items = inbox.get("items") if isinstance(inbox, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _issue_items(config: AppConfig) -> list[dict[str, Any]]:
    queue = _load(config.analytics_dir / "client_issue_queue.json", {})
    issues = queue.get("issues") if isinstance(queue, dict) else []
    return [issue for issue in issues if isinstance(issue, dict)]


def _status_overrides(config: AppConfig) -> dict[str, str]:
    backlog = _load(config.analytics_dir / "trial_fix_backlog.json", {})
    overrides: dict[str, str] = {}
    for item in backlog.get("items", []) if isinstance(backlog, dict) else []:
        if not isinstance(item, dict):
            continue
        status = _normalize_status(str(item.get("status") or ""))
        for key in ("triage_id", "issue_id"):
            value = str(item.get(key) or "")
            if value:
                overrides[value] = status
    return overrides


def _root_cause(category: str, affected_page: str) -> str:
    mapping = {
        "bug": "App behavior needs reproduction and a focused fix.",
        "confusion": "Client-facing copy or flow affordance is not clear enough.",
        "feature_request": "Client requested workflow expansion; scope before implementation.",
        "onboarding": "Handoff or first-run instructions need clarification.",
        "import_issue": "Import bridge, source validation, or folder expectations need review.",
        "export_issue": "Export package readiness or manual upload handoff needs review.",
        "editor_issue": "Editing workflow, approval state, or preview/final asset status needs review.",
        "social_connector_issue": "Connector readiness or live publish gating needs clearer status.",
        "delivery_issue": "Delivery package, manifest, or client review room needs review.",
        "performance": "Runtime performance or packaging size should be measured locally.",
    }
    return mapping.get(category, f"{affected_page or 'App'} workflow needs local triage.")


def _recommended_fix(category: str, severity: str) -> str:
    if severity in {"blocker", "high"}:
        prefix = "Prioritize before the next client session."
    else:
        prefix = "Schedule for the next support pass."
    mapping = {
        "confusion": "Tighten UI copy, add clearer next action text, and update handoff docs.",
        "onboarding": "Update quick start and handoff checklist with the missing step.",
        "import_issue": "Verify import bridge, reproduce with safe fixture media, and improve error copy.",
        "export_issue": "Re-run export dry-runs and clarify manual upload/package readiness.",
        "editor_issue": "Re-run editing safety checks and inspect approval/delivery state.",
        "social_connector_issue": "Keep manual upload fallback visible and verify connector readiness checks.",
        "delivery_issue": "Rebuild delivery room/package manifests and verify originals stay excluded.",
        "performance": "Capture local timing and reduce expensive client-facing steps if reproducible.",
    }
    return f"{prefix} {mapping.get(category, 'Reproduce locally, patch the smallest affected flow, and re-run QA.')}"


def _client_response(category: str, severity: str) -> str:
    if severity in {"blocker", "high"}:
        return "Thanks for flagging this. We have it prioritized for the next patch and will verify it locally before sending an update."
    if category == "feature_request":
        return "Thanks for the request. We logged it for scoping and will separate it from critical trial fixes."
    return "Thanks for the note. We logged it in the local trial issue queue and will include the status in the next trial update."


def build_trial_patch_plan(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    feedback = _feedback_items(config)
    issues = _issue_items(config)
    overrides = _status_overrides(config)
    feedback_by_id = {str(item.get("feedback_id")): item for item in feedback}
    issue_by_feedback: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        for feedback_id in issue.get("feedback_ids", []) if isinstance(issue.get("feedback_ids"), list) else []:
            issue_by_feedback[str(feedback_id)].append(issue)

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in feedback:
        if item.get("status") in {"fixed", "closed"}:
            continue
        category = str(item.get("category") or "other")
        severity = str(item.get("severity") or "medium")
        page = redact_text(str(item.get("related_page") or "Trial Ops"), config.root) or "Trial Ops"
        action = redact_text(str(item.get("related_action") or ""), config.root)
        groups[(severity, category, page or action)].append(item)

    if not groups and issues:
        for issue in issues:
            if issue.get("status") in {"fixed", "closed"}:
                continue
            groups[(str(issue.get("severity") or "medium"), str(issue.get("category") or "other"), "Trial Ops")].append({
                "feedback_id": "",
                "category": issue.get("category") or "other",
                "severity": issue.get("severity") or "medium",
                "related_page": "Trial Ops",
                "related_action": issue.get("title") or "",
                "client_message": "Issue created from QA or trial queue.",
                "status": issue.get("status") or "new",
            })

    now = utc_now()
    triage_items: list[dict[str, Any]] = []
    priority_counter = Counter()
    for (severity, category, page), items in sorted(groups.items(), key=lambda pair: (PRIORITY_BY_SEVERITY.get(pair[0][0], 9), pair[0][1], pair[0][2])):
        feedback_ids = [str(item.get("feedback_id") or "") for item in items if item.get("feedback_id")]
        related_issues: list[dict[str, Any]] = []
        for feedback_id in feedback_ids:
            related_issues.extend(issue_by_feedback.get(feedback_id, []))
        issue_ids = sorted({str(issue.get("issue_id")) for issue in related_issues if issue.get("issue_id")})
        if not issue_ids:
            matching = [issue for issue in issues if issue.get("category") == category and issue.get("severity") == severity]
            issue_ids = sorted({str(issue.get("issue_id")) for issue in matching if issue.get("issue_id")})
        triage_id = "triage_" + _stable_id(severity, category, page, ",".join(feedback_ids), ",".join(issue_ids))
        status = overrides.get(triage_id) or next((overrides.get(issue_id) for issue_id in issue_ids if overrides.get(issue_id)), None) or "triaged"
        priority_counter[severity] += 1
        affected_action = next((redact_text(str(item.get("related_action") or ""), config.root) for item in items if item.get("related_action")), "")
        item = {
            "triage_id": triage_id,
            "feedback_ids": feedback_ids,
            "issue_ids": issue_ids,
            "category": category,
            "severity": severity,
            "priority": PRIORITY_BY_SEVERITY.get(severity, 4),
            "affected_page": redact_text(page, config.root),
            "affected_action": affected_action,
            "likely_root_cause": _root_cause(category, str(page)),
            "recommended_fix": _recommended_fix(category, severity),
            "verification_needed": "Re-run focused flow, client rehearsal, release audit, dashboard JS syntax, and qa:full before release.",
            "client_response": _client_response(category, severity),
            "status": _normalize_status(status),
            "created_at": now,
            "updated_at": now,
            "repeated": len(items) > 1,
            "feedback_count": len(items),
        }
        triage_items.append(item)

    qa = _load(config.analytics_dir / "qa_report.json", {})
    rehearsal = _load(config.analytics_dir / "client_rehearsal_report.json", {})
    audit = _load(config.analytics_dir / "release_candidate_audit.json", {})
    launch = _load(config.analytics_dir / "client_launch_readiness.json", {})
    open_items = [item for item in triage_items if item.get("status") not in {"fixed", "closed", "deferred"}]
    report = {
        "version": 1,
        "updated_at": now,
        "status": "needs_attention" if any(item.get("severity") in {"blocker", "high"} for item in open_items) else "ready",
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "items": triage_items,
        "summary": {
            "total": len(triage_items),
            "open": len(open_items),
            "blockers": len([item for item in open_items if item.get("severity") == "blocker"]),
            "high_priority": len([item for item in open_items if item.get("severity") == "high"]),
            "needs_client_info": len([item for item in open_items if item.get("status") == "needs_client_info"]),
            "qa_status": qa.get("status"),
            "client_rehearsal_status": rehearsal.get("status"),
            "release_audit_status": audit.get("overall_readiness") or audit.get("status"),
            "launch_readiness_status": launch.get("status"),
        },
    }
    patch_plan = {
        "version": 1,
        "updated_at": now,
        "status": report["status"],
        "local_only": True,
        "redacted": True,
        "items": triage_items,
        "next_action": "Resolve blocker/high-priority trial issues first." if report["status"] == "needs_attention" else "Review client response notes before the next trial session.",
    }
    response_notes = {
        "version": 1,
        "updated_at": now,
        "status": "draft",
        "local_only": True,
        "redacted": True,
        "notes": [
            {
                "triage_id": item["triage_id"],
                "feedback_ids": item["feedback_ids"],
                "category": item["category"],
                "severity": item["severity"],
                "status": item["status"],
                "client_response": item["client_response"],
            }
            for item in triage_items
        ],
    }
    backlog = {
        "version": 1,
        "updated_at": now,
        "status": report["status"],
        "local_only": True,
        "redacted": True,
        "items": [
            {
                "triage_id": item["triage_id"],
                "issue_ids": item["issue_ids"],
                "category": item["category"],
                "severity": item["severity"],
                "priority": item["priority"],
                "status": item["status"],
                "recommended_fix": item["recommended_fix"],
                "verification_needed": item["verification_needed"],
                "updated_at": now,
            }
            for item in triage_items
        ],
    }
    risk_summary = {
        "version": 1,
        "updated_at": now,
        "status": report["status"],
        "local_only": True,
        "redacted": True,
        "risks": [
            {
                "risk_id": "risk_" + item["triage_id"].replace("triage_", ""),
                "severity": item["severity"],
                "category": item["category"],
                "client_message": item["client_response"],
                "mitigation": item["recommended_fix"],
            }
            for item in open_items
        ],
    }
    result = {
        "status": report["status"],
        "dry_run": dry_run,
        "feedback_triage_report": report,
        "client_patch_plan": patch_plan,
        "client_response_notes": response_notes,
        "trial_fix_backlog": backlog,
        "trial_risk_summary": risk_summary,
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "feedback_triage_report.json", report)
        save_json_file(config.analytics_dir / "client_patch_plan.json", patch_plan)
        save_json_file(config.analytics_dir / "client_response_notes.json", response_notes)
        save_json_file(config.analytics_dir / "trial_fix_backlog.json", backlog)
        save_json_file(config.analytics_dir / "trial_risk_summary.json", risk_summary)
        _write_patch_docs(config, patch_plan, response_notes, risk_summary)
    return result


def _write_patch_docs(config: AppConfig, patch_plan: dict[str, Any], response_notes: dict[str, Any], risk_summary: dict[str, Any]) -> None:
    out = config.root / "out" / "client_delivery"
    plan_lines = [
        "# Trial Patch Plan",
        "",
        "Feedback stays local. Patch notes are generated for operator review before sending.",
        "",
        f"Status: {patch_plan.get('status')}",
        "",
    ]
    for item in patch_plan.get("items", []):
        plan_lines.extend([
            f"## {item.get('severity', 'medium').title()} - {item.get('category', 'other').replace('_', ' ').title()}",
            f"- Page: {item.get('affected_page') or 'Trial Ops'}",
            f"- Action: {item.get('affected_action') or 'Review locally'}",
            f"- Status: {item.get('status')}",
            f"- Recommended fix: {item.get('recommended_fix')}",
            f"- Verification: {item.get('verification_needed')}",
            "",
        ])
    if not patch_plan.get("items"):
        plan_lines.append("No open client trial patch items are currently planned.")
    _write_text(out / "TRIAL_PATCH_PLAN.md", "\n".join(plan_lines))

    response_lines = [
        "# Client Response Notes",
        "",
        "Draft notes only. Review before sending to a client.",
        "",
    ]
    for note in response_notes.get("notes", []):
        response_lines.extend([
            f"## {note.get('severity', 'medium').title()} - {note.get('category', 'other').replace('_', ' ').title()}",
            f"- Status: {note.get('status')}",
            "",
            str(note.get("client_response") or ""),
            "",
        ])
    if not response_notes.get("notes"):
        response_lines.append("No client response notes are needed yet.")
    _write_text(out / "CLIENT_RESPONSE_NOTES.md", "\n".join(response_lines))

    risk_lines = [
        "# Trial Risk Summary",
        "",
        "Local-only risk summary for operator review.",
        "",
        f"Status: {risk_summary.get('status')}",
        "",
    ]
    for risk in risk_summary.get("risks", []):
        risk_lines.extend([
            f"## {risk.get('severity', 'medium').title()} - {risk.get('category', 'other').replace('_', ' ').title()}",
            f"- Mitigation: {risk.get('mitigation')}",
            "",
        ])
    if not risk_summary.get("risks"):
        risk_lines.append("No open trial risks are currently queued.")
    _write_text(out / "TRIAL_RISK_SUMMARY.md", "\n".join(risk_lines))


def update_trial_issue_status(
    config: AppConfig,
    *,
    issue_id: str = "",
    triage_id: str = "",
    status: str = "triaged",
    note: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_status(status)
    if not issue_id and not triage_id:
        triage = _load(config.analytics_dir / "feedback_triage_report.json", {})
        first = next((item for item in triage.get("items", []) if isinstance(item, dict)), None) if isinstance(triage, dict) else None
        if first:
            triage_id = str(first.get("triage_id") or "")
    now = utc_now()
    note = redact_text(note or "Status updated locally.", config.root)
    backlog = _load(config.analytics_dir / "trial_fix_backlog.json", {})
    if not isinstance(backlog, dict) or not isinstance(backlog.get("items"), list):
        backlog = {"version": 1, "updated_at": now, "local_only": True, "redacted": True, "items": []}
    items = list(backlog.get("items", []))
    matched = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if (triage_id and item.get("triage_id") == triage_id) or (issue_id and issue_id in item.get("issue_ids", [])):
            item["status"] = normalized
            item["operator_note"] = note
            item["updated_at"] = now
            matched = True
    if not matched:
        items.append({
            "triage_id": triage_id,
            "issue_id": issue_id,
            "issue_ids": [issue_id] if issue_id else [],
            "status": normalized,
            "operator_note": note,
            "updated_at": now,
        })
    backlog["items"] = items
    backlog["updated_at"] = now

    queue = _load(config.analytics_dir / "client_issue_queue.json", {})
    if isinstance(queue, dict) and isinstance(queue.get("issues"), list):
        for issue in queue["issues"]:
            if isinstance(issue, dict) and issue_id and issue.get("issue_id") == issue_id:
                issue["status"] = normalized
                issue["updated_at"] = now
        queue["updated_at"] = now

    response = _load(config.analytics_dir / "client_response_notes.json", {})
    if not isinstance(response, dict):
        response = {"version": 1, "updated_at": now, "status": "draft", "local_only": True, "redacted": True, "notes": []}
    notes = response.get("notes") if isinstance(response.get("notes"), list) else []
    notes.append({
        "triage_id": triage_id,
        "issue_id": issue_id,
        "status": normalized,
        "client_response": "We updated this item in the local trial patch backlog. The operator will review before sending.",
        "operator_note": note,
        "updated_at": now,
    })
    response["notes"] = notes
    response["updated_at"] = now

    if not dry_run:
        save_json_file(config.analytics_dir / "trial_fix_backlog.json", backlog)
        if isinstance(queue, dict):
            save_json_file(config.analytics_dir / "client_issue_queue.json", queue)
        save_json_file(config.analytics_dir / "client_response_notes.json", response)
    return {
        "status": "pass",
        "dry_run": dry_run,
        "issue_id": issue_id,
        "triage_id": triage_id,
        "new_status": normalized,
        "trial_fix_backlog": "analytics/trial_fix_backlog.json",
        "client_response_notes": "analytics/client_response_notes.json",
    }
