from __future__ import annotations

from pathlib import Path
from typing import Any

from .client_feedback import redact_text
from .config import AppConfig
from .index import utc_now
from .json_store import load_json_file, save_json_file


def _load(path: Path, fallback: Any) -> Any:
    return load_json_file(path, fallback)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _items(data: Any, key: str = "items") -> list[dict[str, Any]]:
    values = data.get(key) if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _redact(value: Any, config: AppConfig) -> str:
    return redact_text(str(value or ""), config.root)


def _status_count(items: list[dict[str, Any]], *statuses: str) -> int:
    allowed = set(statuses)
    return len([item for item in items if str(item.get("status") or "").lower() in allowed])


def _scorecard_status(score: int, blocker_count: int, open_issue_count: int) -> str:
    if blocker_count > 0:
        return "blocked"
    if score >= 85 and open_issue_count == 0:
        return "successful"
    if score >= 65:
        return "promising"
    return "needs_attention"


def _safe_status(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else default


def build_trial_success_report(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    feedback_inbox = _load(config.analytics_dir / "client_feedback_inbox.json", {})
    feedback_summary = _load(config.analytics_dir / "client_feedback_summary.json", {})
    issue_queue = _load(config.analytics_dir / "client_issue_queue.json", {})
    triage = _load(config.analytics_dir / "feedback_triage_report.json", {})
    patch_plan = _load(config.analytics_dir / "client_patch_plan.json", {})
    patch_board = _load(config.analytics_dir / "patch_execution_board.json", {})
    patch_verification = _load(config.analytics_dir / "patch_verification_plan.json", {})
    client_patch_status = _load(config.analytics_dir / "client_patch_status.json", {})
    patch_release_notes = _load(config.analytics_dir / "patch_release_notes.json", {})
    client_release_notes = _load(config.analytics_dir / "client_release_notes.json", {})
    fix_backlog = _load(config.analytics_dir / "trial_fix_backlog.json", {})
    risk_summary = _load(config.analytics_dir / "trial_risk_summary.json", {})
    qa_report = _load(config.analytics_dir / "qa_report.json", {})
    audit = _load(config.analytics_dir / "release_candidate_audit.json", {})
    rehearsal = _load(config.analytics_dir / "client_rehearsal_report.json", {})
    launch = _load(config.analytics_dir / "client_launch_readiness.json", {})

    feedback_items = _items(feedback_inbox)
    issue_items = _items(issue_queue, "issues")
    triage_items = _items(triage) or _items(patch_plan)
    patch_items = _items(patch_board)
    risk_items = _items(risk_summary, "risks")
    release_items = _items(client_release_notes)

    feedback_count = int(feedback_summary.get("total") or len(feedback_items)) if isinstance(feedback_summary, dict) else len(feedback_items)
    blocker_count = len([item for item in feedback_items + issue_items + triage_items if str(item.get("severity") or "").lower() == "blocker"])
    high_priority_count = len([item for item in feedback_items + issue_items + triage_items if str(item.get("severity") or "").lower() == "high"])
    fixed_count = _status_count(triage_items + patch_items + _items(fix_backlog), "fixed")
    verified_count = _status_count(patch_items, "verified", "ready_for_release", "closed")
    needs_client_info_count = _status_count(feedback_items + issue_items + triage_items, "needs_client_info")
    open_issue_count = len([
        item for item in issue_items + triage_items + patch_items
        if str(item.get("status") or "new").lower() not in {"fixed", "verified", "ready_for_release", "closed", "deferred"}
    ])

    qa_status = _safe_status(qa_report.get("status") if isinstance(qa_report, dict) else None)
    audit_status = _safe_status(audit.get("overall_readiness") or audit.get("status") if isinstance(audit, dict) else None)
    rehearsal_status = _safe_status(rehearsal.get("status") if isinstance(rehearsal, dict) else None)
    launch_status = _safe_status(launch.get("status") if isinstance(launch, dict) else None)
    manual_upload_status = "ready" if audit_status in {"ready", "pass"} and rehearsal_status == "pass" else "needs_attention"
    editing_delivery_status = "ready" if audit.get("overall_readiness") == "ready" else "needs_attention" if isinstance(audit, dict) else "unknown"
    social_connector_status = "manual_upload_ready" if manual_upload_status == "ready" else "needs_attention"

    readiness_score = 100
    readiness_score -= min(blocker_count * 25, 60)
    readiness_score -= min(high_priority_count * 10, 30)
    readiness_score -= min(open_issue_count * 5, 25)
    if qa_status not in {"pass", "warn"}:
        readiness_score -= 15
    if audit_status != "ready":
        readiness_score -= 15
    if rehearsal_status != "pass":
        readiness_score -= 15
    readiness_score = max(0, min(100, readiness_score))
    overall_status = _scorecard_status(readiness_score, blocker_count, open_issue_count)

    client_next_step = "Review the client trial summary and schedule the next trial pass." if overall_status in {"successful", "promising"} else "Resolve blocker and high-priority trial items before the next client session."
    operator_next_step = "Build release notes, verify the next trial checklist, and keep manual upload guidance visible." if overall_status in {"successful", "promising"} else "Use Trial Ops to prioritize open blockers, rerun client rehearsal, and rebuild this success report."

    scorecard = {
        "version": 1,
        "updated_at": now,
        "local_only": True,
        "redacted": True,
        "overall_status": overall_status,
        "readiness_score": readiness_score,
        "feedback_count": feedback_count,
        "blocker_count": blocker_count,
        "high_priority_count": high_priority_count,
        "fixed_count": fixed_count,
        "verified_count": verified_count,
        "needs_client_info_count": needs_client_info_count,
        "open_issue_count": open_issue_count,
        "client_next_step": client_next_step,
        "operator_next_step": operator_next_step,
        "manual_upload_status": manual_upload_status,
        "editing_delivery_status": editing_delivery_status,
        "social_connector_status": social_connector_status,
        "launch_readiness_status": launch_status,
    }

    what_worked = [
        "Client rehearsal completed locally." if rehearsal_status == "pass" else "Client rehearsal needs another pass.",
        "Release audit is ready." if audit_status == "ready" else "Release audit needs attention.",
        "Manual upload remains available and local-first.",
        "Support and trial outputs remain redacted by default.",
    ]
    what_changed = [
        _redact(item.get("title") or item.get("client_note") or item.get("patch_id"), config)
        for item in release_items[:8]
    ] or ["No verified client release-note items are ready yet."]
    unresolved = [
        {
            "title": _redact(item.get("title") or item.get("category") or "Trial issue", config),
            "status": _redact(item.get("status") or "open", config),
            "severity": _redact(item.get("severity") or "medium", config),
        }
        for item in (issue_items + triage_items + patch_items)
        if str(item.get("status") or "new").lower() not in {"fixed", "verified", "ready_for_release", "closed", "deferred"}
    ][:12]

    trial_success = {
        "version": 1,
        "updated_at": now,
        "status": overall_status,
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
        "scorecard": scorecard,
        "what_was_tested": [
            "Import, processing, review, export, manual upload handoff, Trial Ops, support package, launch audit, and client rehearsal.",
            f"QA status: {qa_status}. Release audit: {audit_status}. Client rehearsal: {rehearsal_status}.",
        ],
        "what_worked": what_worked,
        "what_changed": what_changed,
        "unresolved_issues": unresolved,
        "risks": risk_items[:8],
    }
    client_success = {
        "version": 1,
        "updated_at": now,
        "status": overall_status,
        "local_only": True,
        "redacted": True,
        "scorecard": scorecard,
        "client_summary": "HigherKey trial results are summarized locally. Reports are drafts for operator review before sharing.",
        "what_worked": what_worked,
        "what_changed": what_changed,
        "still_needs_attention": unresolved,
    }
    internal_analysis = {
        "version": 1,
        "updated_at": now,
        "status": overall_status,
        "local_only": True,
        "redacted": True,
        "scorecard": scorecard,
        "qa_status": qa_status,
        "release_audit_status": audit_status,
        "client_rehearsal_status": rehearsal_status,
        "patch_verification_status": patch_verification.get("status") if isinstance(patch_verification, dict) else "unknown",
        "client_patch_status": client_patch_status.get("status") if isinstance(client_patch_status, dict) else "unknown",
        "patch_release_notes_status": patch_release_notes.get("status") if isinstance(patch_release_notes, dict) else "unknown",
        "operator_analysis": operator_next_step,
        "unresolved_issues": unresolved,
    }
    next_plan = {
        "version": 1,
        "updated_at": now,
        "status": "ready" if overall_status in {"successful", "promising"} else "needs_attention",
        "local_only": True,
        "redacted": True,
        "client_next_step": client_next_step,
        "operator_next_step": operator_next_step,
        "steps": [
            "Review unresolved trial items in Trial Ops.",
            "Build or refresh client release notes after verified fixes.",
            "Run client rehearsal and release audit before the next client session.",
            "Share only reviewed client-facing summaries; no messages are sent automatically.",
        ],
    }
    result = {
        "status": overall_status,
        "dry_run": dry_run,
        "trial_success_report": trial_success,
        "client_trial_success_report": client_success,
        "internal_trial_analysis": internal_analysis,
        "next_trial_plan": next_plan,
        "client_trial_scorecard": scorecard,
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "trial_success_report.json", trial_success)
        save_json_file(config.analytics_dir / "client_trial_success_report.json", client_success)
        save_json_file(config.analytics_dir / "internal_trial_analysis.json", internal_analysis)
        save_json_file(config.analytics_dir / "next_trial_plan.json", next_plan)
        save_json_file(config.analytics_dir / "client_trial_scorecard.json", scorecard)
        _write_docs(config, trial_success, client_success, internal_analysis, next_plan)
    return result


def _write_docs(
    config: AppConfig,
    trial_success: dict[str, Any],
    client_success: dict[str, Any],
    internal_analysis: dict[str, Any],
    next_plan: dict[str, Any],
) -> None:
    out = config.root / "out" / "client_delivery"
    scorecard = trial_success.get("scorecard", {})
    success_lines = [
        "# Trial Success Report",
        "",
        "Local trial success report. Review before sharing.",
        "",
        f"Overall status: {scorecard.get('overall_status')}",
        f"Readiness score: {scorecard.get('readiness_score')}",
        "",
        "## What Was Tested",
        "",
        *[f"- {item}" for item in trial_success.get("what_was_tested", [])],
        "",
        "## What Worked",
        "",
        *[f"- {item}" for item in trial_success.get("what_worked", [])],
        "",
        "## What Changed",
        "",
        *[f"- {item}" for item in trial_success.get("what_changed", [])],
        "",
        "## Still Needs Attention",
        "",
    ]
    unresolved = trial_success.get("unresolved_issues", [])
    success_lines.extend([f"- {item.get('severity')}: {item.get('title')} ({item.get('status')})" for item in unresolved] or ["- No unresolved trial issues are listed."])
    _write_text(out / "TRIAL_SUCCESS_REPORT.md", "\n".join(success_lines))

    client_lines = [
        "# Client Trial Summary",
        "",
        "Draft client-facing summary. No message is sent automatically.",
        "",
        f"Overall status: {scorecard.get('overall_status')}",
        f"Readiness score: {scorecard.get('readiness_score')}",
        "",
        str(client_success.get("client_summary") or ""),
        "",
        "## Next Step",
        "",
        str(scorecard.get("client_next_step") or ""),
        "",
    ]
    _write_text(out / "CLIENT_TRIAL_SUMMARY.md", "\n".join(client_lines))

    next_lines = [
        "# Next Trial Plan",
        "",
        "Local plan for the next client trial pass.",
        "",
        f"Client next step: {next_plan.get('client_next_step')}",
        f"Operator next step: {next_plan.get('operator_next_step')}",
        "",
    ]
    next_lines.extend([f"- {step}" for step in next_plan.get("steps", [])])
    _write_text(out / "NEXT_TRIAL_PLAN.md", "\n".join(next_lines))

    internal_lines = [
        "# Internal Trial Analysis",
        "",
        "Internal operator analysis. Keep local unless reviewed for sharing.",
        "",
        f"QA status: {internal_analysis.get('qa_status')}",
        f"Release audit: {internal_analysis.get('release_audit_status')}",
        f"Client rehearsal: {internal_analysis.get('client_rehearsal_status')}",
        f"Patch verification: {internal_analysis.get('patch_verification_status')}",
        "",
        str(internal_analysis.get("operator_analysis") or ""),
    ]
    _write_text(out / "INTERNAL_TRIAL_ANALYSIS.md", "\n".join(internal_lines))
