from __future__ import annotations

from typing import Any

from .client_feedback import redact_text
from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


def _load(config: AppConfig, filename: str, fallback: Any) -> Any:
    return load_json_file(config.analytics_dir / filename, fallback)


def _items(data: Any, key: str = "items") -> list[dict[str, Any]]:
    values = data.get(key) if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _redact(value: Any, config: AppConfig) -> str:
    return redact_text(str(value or ""), config.root)


def _write_text(config: AppConfig, filename: str, text: str) -> None:
    path = config.root / "out" / "client_delivery" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _status_count(items: list[dict[str, Any]], *statuses: str) -> int:
    allowed = {status.lower() for status in statuses}
    return len([item for item in items if str(item.get("status") or "").lower() in allowed])


def _safe_status(data: Any, key: str = "status", default: str = "unknown") -> str:
    if isinstance(data, dict):
        value = str(data.get(key) or "").strip()
        return value or default
    return default


READY_STATUSES = {"ready", "pass", "passed", "successful", "ok"}
SKIPPED_STATUSES = {"skipped", "not_applicable", "not_required"}
ATTENTION_STATUSES = {"needs_attention", "warn", "warning", "missing", "fail", "failed", "blocked", "not_ready"}


def _ready_or_skipped(status: str) -> bool:
    return str(status or "").strip().lower() in READY_STATUSES | SKIPPED_STATUSES


def _int_value(data: Any, key: str, default: int = 0) -> int:
    if not isinstance(data, dict):
        return default
    try:
        return int(data.get(key) or default)
    except (TypeError, ValueError):
        return default


def _issue_count(items: list[dict[str, Any]], *statuses: str) -> int:
    wanted = {status.lower() for status in statuses}
    return len([item for item in items if str(item.get("status") or "").lower() in wanted])


def _issue_severity_count(items: list[dict[str, Any]], *severities: str) -> int:
    wanted = {severity.lower() for severity in severities}
    return len([item for item in items if str(item.get("severity") or "").lower() in wanted])


def _decision(score: int, reasons: list[str], blockers: int, high_priority: int, open_issues: int) -> tuple[str, str]:
    if blockers > 0:
        return "blocked", "next_trial_required"
    if reasons:
        return "needs_attention", "next_trial_required"
    if high_priority > 0:
        return "needs_attention", "next_trial_required"
    if open_issues > 0:
        return ("promising" if score >= 65 else "needs_attention", "next_trial_recommended")
    if score >= 85:
        return "successful", "production_ready_review"
    if score >= 65:
        return "promising", "next_trial_recommended"
    return "needs_attention", "needs_attention"


def _markdown_list(values: list[str], empty: str) -> list[str]:
    return [f"- {value}" for value in values] if values else [f"- {empty}"]


def build_client_success_dashboard(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    trial_report = _load(config, "trial_success_report.json", {})
    client_trial_report = _load(config, "client_trial_success_report.json", {})
    scorecard = _load(config, "client_trial_scorecard.json", {})
    next_trial_plan = _load(config, "next_trial_plan.json", {})
    delivery_manifest = _load(config, "client_delivery_manifest.json", {})
    delivery_checklist = _load(config, "client_delivery_checklist.json", {})
    delivery_verification = _load(config, "edited_delivery_package_verification.json", {})
    editing_delivery_state = _load(config, "client_editing_delivery_state.json", {})
    social_connection = _load(config, "client_social_connection_status.json", {})
    live_publish_readiness = _load(config, "client_live_publish_readiness.json", {})
    launch = _load(config, "client_launch_readiness.json", {})
    audit = _load(config, "release_candidate_audit.json", {})
    rehearsal = _load(config, "client_rehearsal_report.json", {})
    qa_report = _load(config, "qa_report.json", {})
    issue_queue = _load(config, "client_issue_queue.json", {})
    patch_board = _load(config, "patch_execution_board.json", {})
    patch_status = _load(config, "client_patch_status.json", {})
    client_release_notes = _load(config, "client_release_notes.json", {})
    risk_summary = _load(config, "trial_risk_summary.json", {})
    support_status = _load(config, "client_support_status.json", {})

    issues = _items(issue_queue, "issues")
    if not issues:
        issues = _items(issue_queue)
    patches = _items(patch_board)
    risks = _items(risk_summary, "risks")
    release_items = _items(client_release_notes)
    checklist = _items(delivery_manifest, "checklist")
    delivery_checklist_items = _items(delivery_checklist)
    editing_delivery_items = _items(editing_delivery_state)

    readiness_score = _int_value(scorecard, "readiness_score")
    blocker_count = _int_value(scorecard, "blocker_count", _issue_severity_count(issues, "blocker"))
    high_priority_count = _int_value(scorecard, "high_priority_count", _issue_severity_count(issues, "high"))
    needs_client_info_count = _int_value(scorecard, "needs_client_info_count", _issue_count(issues, "needs_client_info"))
    open_issue_count = _int_value(scorecard, "open_issue_count", len([item for item in issues if str(item.get("status") or "new").lower() not in {"fixed", "verified", "ready_for_release", "closed", "deferred"}]))
    fixed_count = _int_value(scorecard, "fixed_count", _status_count(patches, "fixed"))
    verified_count = _int_value(scorecard, "verified_count", _status_count(patches, "verified", "ready_for_release", "closed"))
    launch_status = _safe_status(launch) if _safe_status(launch) != "unknown" else _safe_status(scorecard, "launch_readiness_status", "unknown")
    audit_status = _safe_status(audit, "overall_readiness")
    rehearsal_status = _safe_status(rehearsal)
    delivery_status = _safe_status(delivery_verification, default="not_verified")
    support_package_status = _safe_status(support_status, default="ready")
    delivery_manifest_status = _safe_status(delivery_manifest)
    delivery_checklist_attention = len([item for item in delivery_checklist_items if str(item.get("status") or "").lower() in ATTENTION_STATUSES])
    edited_delivery_not_ready = len([item for item in editing_delivery_items if str(item.get("delivery_status") or "").lower() in {"not_ready", "needs_revision"}])
    manual_upload_status = _safe_status(scorecard, "manual_upload_status", "available")
    social_connector_status = _safe_status(scorecard, "social_connector_status", _safe_status(social_connection, default="manual_upload"))
    live_publish_status = _safe_status(live_publish_readiness, default="manual_upload")
    qa_status = _safe_status(qa_report, default="unknown")
    patch_status_value = _safe_status(patch_status, default="unknown")

    readiness_blockers: list[str] = []
    needs_attention_reasons: list[str] = []
    if blocker_count > 0:
        readiness_blockers.append(f"{blocker_count} blocker issue(s) remain.")
    if high_priority_count > 0:
        needs_attention_reasons.append(f"{high_priority_count} high-priority issue(s) remain.")
    if needs_client_info_count > 0:
        needs_attention_reasons.append(f"{needs_client_info_count} issue(s) still need client information.")
    if open_issue_count > 0:
        needs_attention_reasons.append(f"{open_issue_count} open issue(s) require operator or client action.")
    if not _ready_or_skipped(launch_status):
        needs_attention_reasons.append(f"Launch readiness is {launch_status}.")
    if not _ready_or_skipped(delivery_status):
        needs_attention_reasons.append(f"Edited delivery package verification is {delivery_status}.")
    if delivery_manifest_status not in {"unknown"} and not _ready_or_skipped(delivery_manifest_status):
        needs_attention_reasons.append(f"Client delivery manifest is {delivery_manifest_status}.")
    if delivery_checklist_attention:
        needs_attention_reasons.append(f"{delivery_checklist_attention} client delivery checklist item(s) need attention.")
    if edited_delivery_not_ready:
        needs_attention_reasons.append("Edited delivery has items not ready for delivery.")
    if support_package_status not in {"unknown"} and not _ready_or_skipped(support_package_status):
        needs_attention_reasons.append(f"Support package status is {support_package_status}.")
    if audit_status not in {"unknown"} and not _ready_or_skipped(audit_status):
        needs_attention_reasons.append(f"Release audit is {audit_status}.")
    if rehearsal_status not in {"unknown"} and not _ready_or_skipped(rehearsal_status):
        needs_attention_reasons.append(f"Client rehearsal is {rehearsal_status}.")
    if qa_status not in {"unknown", "warn"} and not _ready_or_skipped(qa_status):
        needs_attention_reasons.append(f"QA status is {qa_status}.")

    social_ready = _ready_or_skipped(social_connector_status) and _ready_or_skipped(live_publish_status)
    manual_upload_required = not social_ready or str(manual_upload_status).lower() in {"ready", "available", "needs_attention", "manual_upload"}
    if manual_upload_required:
        needs_attention_reasons.append("Manual upload remains the safe fallback until official connector readiness and approval gates are complete.")

    overall_status, decision = _decision(readiness_score, readiness_blockers + needs_attention_reasons, blocker_count, high_priority_count, open_issue_count)

    delivered_items = [
        _redact(item.get("title") or item.get("client_message") or item.get("id"), config)
        for item in checklist
        if str(item.get("status") or "").lower() == "ready"
    ][:10]
    changed_items = [
        _redact(item.get("title") or item.get("client_note") or item.get("patch_id"), config)
        for item in release_items[:10]
    ]
    remaining_risks = [
        _redact(item.get("title") or item.get("risk") or item.get("category") or "Trial risk", config)
        for item in risks[:10]
    ]
    if open_issue_count:
        remaining_risks.extend([
            _redact(item.get("title") or item.get("category") or "Open trial issue", config)
            for item in issues
            if str(item.get("status") or "new").lower() not in {"fixed", "verified", "ready_for_release", "closed", "deferred"}
        ][:8])
    remaining_risks = remaining_risks[:12] or ["No unresolved client trial risks are listed."]

    next_steps = [
        _redact(step, config)
        for step in (next_trial_plan.get("steps") if isinstance(next_trial_plan, dict) and isinstance(next_trial_plan.get("steps"), list) else [])
    ]
    if decision == "production_ready_review":
        next_steps = ["Review production-readiness with the operator.", "Confirm support package and manual upload handoff remain current.", *next_steps]
    elif decision == "next_trial_required":
        next_steps = ["Resolve blockers or readiness gaps before closeout.", "Run client rehearsal and launch audit again.", *next_steps]
    elif decision == "next_trial_recommended":
        next_steps = ["Run another client trial pass after reviewing remaining risks.", *next_steps]
    elif not next_steps:
        next_steps = ["Run another trial pass after reviewing open issues."]
    if manual_upload_required:
        next_steps = ["Use manual upload for client delivery until official connector readiness and approval gates are complete.", *next_steps]

    dashboard = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if overall_status in {"successful", "promising"} and not readiness_blockers and not needs_attention_reasons else "needs_attention",
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "external_messaging": False,
        "success_summary": {
            "overall_status": overall_status,
            "readiness_score": readiness_score,
            "trial_status": _safe_status(trial_report),
            "launch_readiness": launch_status,
            "release_audit": audit_status,
            "client_rehearsal": rehearsal_status,
            "delivery_verification": delivery_status,
            "delivery_manifest": delivery_manifest_status,
            "support_package": support_package_status,
            "manual_upload_status": manual_upload_status,
            "social_connector_status": social_connector_status,
            "live_publish_status": live_publish_status,
            "qa_status": qa_status,
        },
        "counts": {
            "fixed": fixed_count,
            "verified": verified_count,
            "open_issues": open_issue_count,
            "blockers": blocker_count,
            "high_priority": high_priority_count,
            "needs_client_info": needs_client_info_count,
            "delivered_items": len(delivered_items),
            "remaining_risks": len(remaining_risks),
        },
        "readiness_blockers": readiness_blockers,
        "needs_attention_reasons": needs_attention_reasons,
        "open_risks": remaining_risks,
        "what_was_delivered": delivered_items or ["Client handoff and trial documentation are available for review."],
        "what_changed": changed_items or ["No verified client release-note items are ready yet."],
        "remaining_risks": remaining_risks,
        "recommended_next_steps": next_steps[:10],
        "decision": decision,
        "next_engagement_recommendation": decision,
        "client_next_step": next_steps[0] if next_steps else "Review closeout report.",
        "operator_next_step": "Review closeout, support package, manual upload guidance, and next engagement recommendation before sharing.",
        "manual_upload_required": manual_upload_required,
    }
    closeout = {
        "version": 1,
        "updated_at": now,
        "status": dashboard["status"],
        "local_only": True,
        "redacted": True,
        "client_message": "Client trial closeout is generated locally for operator review before sharing.",
        "success_summary": dashboard["success_summary"],
        "readiness_blockers": readiness_blockers,
        "needs_attention_reasons": needs_attention_reasons,
        "open_risks": dashboard["open_risks"],
        "what_was_delivered": dashboard["what_was_delivered"],
        "remaining_risks": dashboard["remaining_risks"],
        "recommended_next_steps": dashboard["recommended_next_steps"],
        "decision": decision,
        "client_next_step": dashboard["client_next_step"],
        "operator_next_step": dashboard["operator_next_step"],
        "next_engagement_recommendation": decision,
        "manual_upload_required": manual_upload_required,
    }
    checklist_payload = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if dashboard["status"] == "ready" else "needs_attention",
        "local_only": True,
        "redacted": True,
        "items": [
            {"id": "review_success_report", "title": "Review trial success report", "status": "ready" if trial_report else "missing", "next_action": "Build Trial Success Report"},
            {"id": "review_release_notes", "title": "Review client release notes", "status": "ready" if release_items else "needs_attention", "next_action": "Build Client Release Notes"},
            {"id": "verify_handoff", "title": "Verify handoff package safety", "status": "ready" if audit_status == "ready" else "needs_attention", "next_action": "Run Launch Audit"},
            {"id": "verify_rehearsal", "title": "Verify client rehearsal", "status": "ready" if rehearsal_status == "pass" else "needs_attention", "next_action": "Run Client Rehearsal"},
            {"id": "confirm_manual_upload", "title": "Confirm manual upload fallback", "status": "ready", "next_action": "Keep manual upload instructions visible"},
            {"id": "review_risks", "title": "Review remaining risks", "status": "ready" if not readiness_blockers and not needs_attention_reasons else "needs_attention", "next_action": "Resolve blockers and needs-attention items before closeout"},
            {"id": "confirm_delivery", "title": "Confirm edited delivery readiness", "status": "ready" if _ready_or_skipped(delivery_status) else "needs_attention", "next_action": "Verify Edited Delivery"},
        ],
    }
    recommendation = {
        "version": 1,
        "updated_at": now,
        "status": dashboard["status"],
        "local_only": True,
        "redacted": True,
        "decision": decision,
        "client_next_step": next_steps[0] if next_steps else "Review closeout report.",
        "operator_next_step": dashboard["operator_next_step"],
        "production_readiness_review": decision == "production_ready_review",
        "next_trial_recommended": decision in {"next_trial_required", "next_trial_recommended", "needs_attention"},
        "no_automatic_messaging": True,
        "manual_upload_recommended": manual_upload_required,
        "manual_upload_required": manual_upload_required,
        "live_posting_ready": social_ready,
        "readiness_blockers": readiness_blockers,
        "needs_attention_reasons": needs_attention_reasons,
        "open_risks": dashboard["open_risks"],
    }
    summary_payload = {
        "version": 1,
        "updated_at": now,
        "status": dashboard["status"],
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "external_messaging": False,
        "client_message": "Client success summary is generated locally for operator review before sharing.",
        "overall_trial_result": overall_status,
        "readiness_score": readiness_score,
        "decision": decision,
        "readiness_blockers": readiness_blockers,
        "needs_attention_reasons": needs_attention_reasons,
        "open_risks": dashboard["open_risks"],
        "what_was_delivered": dashboard["what_was_delivered"],
        "remaining_risks": dashboard["remaining_risks"],
        "client_next_step": recommendation["client_next_step"],
        "operator_next_step": recommendation["operator_next_step"],
        "manual_upload_required": manual_upload_required,
        "next_engagement_recommendation": decision,
    }
    result = {
        "status": dashboard["status"],
        "dry_run": dry_run,
        "client_success_dashboard": dashboard,
        "client_trial_closeout_report": closeout,
        "operator_closeout_checklist": checklist_payload,
        "next_engagement_recommendation": recommendation,
        "client_success_summary": summary_payload,
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "client_success_dashboard.json", dashboard)
        save_json_file(config.analytics_dir / "client_trial_closeout_report.json", closeout)
        save_json_file(config.analytics_dir / "operator_closeout_checklist.json", checklist_payload)
        save_json_file(config.analytics_dir / "next_engagement_recommendation.json", recommendation)
        save_json_file(config.analytics_dir / "client_success_summary.json", summary_payload)
        _write_docs(config, dashboard, closeout, checklist_payload, recommendation, summary_payload)
    return result


def _write_docs(
    config: AppConfig,
    dashboard: dict[str, Any],
    closeout: dict[str, Any],
    checklist: dict[str, Any],
    recommendation: dict[str, Any],
    summary_payload: dict[str, Any],
) -> None:
    summary = dashboard.get("success_summary", {})
    _write_text(config, "CLIENT_SUCCESS_DASHBOARD.md", "\n".join([
        "# Client Success Dashboard",
        "",
        "Local client success summary. Review before sharing.",
        "",
        f"Overall status: {summary.get('overall_status')}",
        f"Readiness score: {summary.get('readiness_score')}",
        f"Decision: {dashboard.get('decision')}",
        "",
        "## What Was Delivered",
        *_markdown_list(dashboard.get("what_was_delivered", []), "No delivered items listed."),
        "",
        "## What Changed",
        *_markdown_list(dashboard.get("what_changed", []), "No verified changes listed."),
        "",
        "## Remaining Risks",
        *_markdown_list(dashboard.get("remaining_risks", []), "No remaining risks listed."),
    ]))
    _write_text(config, "TRIAL_CLOSEOUT_REPORT.md", "\n".join([
        "# Trial Closeout Report",
        "",
        str(closeout.get("client_message") or "Review before sharing."),
        "",
        f"Status: {closeout.get('status')}",
        f"Decision: {closeout.get('decision')}",
        "",
        "## Recommended Next Steps",
        *_markdown_list(closeout.get("recommended_next_steps", []), "Review closeout locally."),
    ]))
    checklist_lines = [
        "# Operator Closeout Checklist",
        "",
        "Local operator checklist. No client message is sent automatically.",
        "",
    ]
    for item in checklist.get("items", []):
        checklist_lines.append(f"- [{item.get('status')}] {item.get('title')} - {item.get('next_action')}")
    _write_text(config, "OPERATOR_CLOSEOUT_CHECKLIST.md", "\n".join(checklist_lines))
    _write_text(config, "NEXT_ENGAGEMENT_RECOMMENDATION.md", "\n".join([
        "# Next Engagement Recommendation",
        "",
        "Draft recommendation for operator review.",
        "",
        f"Decision: {recommendation.get('decision')}",
        f"Client next step: {recommendation.get('client_next_step')}",
        f"Operator next step: {recommendation.get('operator_next_step')}",
        f"Production-readiness review: {recommendation.get('production_readiness_review')}",
        f"Next trial recommended: {recommendation.get('next_trial_recommended')}",
        "",
        "No message is sent automatically.",
    ]))
    _write_text(config, "CLIENT_SUCCESS_SUMMARY.md", "\n".join([
        "# Client Success Summary",
        "",
        str(summary_payload.get("client_message") or "Review before sharing."),
        "",
        f"Overall trial result: {summary_payload.get('overall_trial_result')}",
        f"Readiness score: {summary_payload.get('readiness_score')}",
        f"Decision: {summary_payload.get('decision')}",
        "",
        "## What Was Delivered",
        *_markdown_list(summary_payload.get("what_was_delivered", []), "No delivered items listed."),
        "",
        "## Remaining Risks",
        *_markdown_list(summary_payload.get("remaining_risks", []), "No remaining risks listed."),
        "",
        "## Next Step",
        f"Client: {summary_payload.get('client_next_step')}",
        f"Operator: {summary_payload.get('operator_next_step')}",
        "",
        "No message is sent automatically.",
    ]))
