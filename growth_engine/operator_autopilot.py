from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .audit import write_audit_event
from .config import load_config
from .index import relative_path, utc_now
from .marketing_intelligence import load_json, safe_list, write_json, write_text


SAFE_AUTO_COMMANDS: dict[str, list[str]] = {
    "build_marketing_plan": ["python3", "scripts/build_marketing_plan.py"],
    "build_campaign_plan": ["python3", "scripts/build_campaign_plan.py"],
    "build_growth_strategy": ["python3", "scripts/build_growth_strategy.py"],
    "build_creative_direction": ["python3", "scripts/build_creative_direction.py"],
    "build_production_command": ["python3", "scripts/build_production_command.py"],
    "build_media_cache": ["python3", "scripts/build_media_cache.py"],
    "build_client_workflow": ["python3", "scripts/build_client_workflow.py"],
    "build_runtime_snapshot": ["python3", "scripts/build_runtime_snapshot.py"],
    "build_task_snapshot": ["python3", "scripts/build_task_snapshot.py"],
    "build_observability_report": ["python3", "scripts/build_observability_report.py"],
    "build_trial_readiness_report": ["python3", "scripts/build_trial_readiness_report.py"],
}

APPROVAL_REQUIRED_CATEGORIES = {
    "approve",
    "reject",
    "export",
    "archive",
    "reset",
    "repair",
    "record_results",
    "upload",
    "mark_uploaded",
}

BLOCKED_TERMS = {
    "delete original",
    "post to social",
    "social posting",
    "remote platform call",
    "live platform integration",
    "live api",
    "overwrite source",
    "external account",
}


def _load_inputs(root: Path) -> dict[str, Any]:
    analytics = root / "analytics"
    return {
        "production_command_center": load_json(analytics / "production_command_center.json", {}),
        "today_action_plan": load_json(analytics / "today_action_plan.json", {}),
        "content_readiness_board": load_json(analytics / "content_readiness_board.json", {}),
        "operator_priorities": load_json(analytics / "operator_priorities.json", {}),
        "client_daily_plan": load_json(analytics / "client_daily_plan.json", {}),
        "creative_director_brief": load_json(analytics / "creative_director_brief.json", {}),
        "client_creative_plan": load_json(analytics / "client_creative_plan.json", {}),
        "growth_dashboard": load_json(analytics / "growth_dashboard.json", {}),
        "next_best_actions": load_json(analytics / "next_best_actions.json", {}),
        "campaign_board": load_json(analytics / "campaign_board.json", {}),
        "posting_schedule": load_json(analytics / "posting_schedule.json", {}),
        "manual_post_status": load_json(analytics / "manual_post_status.json", {}),
        "review_queue": load_json(root / "queue" / "review_queue.json", {}),
        "approved_reviews": load_json(root / "queue" / "approved_reviews.json", {}),
        "social_manifest": load_json(root / "out" / "social_exports" / "manifest.json", {}),
        "previous_history": load_json(analytics / "autopilot_run_history.json", {}),
        "previous_receipts": load_json(analytics / "autopilot_approval_receipts.json", {}),
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return f"{prefix}_{digest.hexdigest()[:12]}"


def _today_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    plan = data.get("today_action_plan") or {}
    actions = safe_list(plan.get("actions"))
    if actions:
        return [item for item in actions if isinstance(item, dict)]
    command = data.get("production_command_center") or {}
    nested = command.get("today_action_plan") if isinstance(command.get("today_action_plan"), dict) else {}
    return [item for item in safe_list(nested.get("actions")) if isinstance(item, dict)]


def _title_to_safe_key(title: str, category: str) -> str | None:
    lower = f"{title} {category}".lower()
    mapping = [
        ("creative", "build_creative_direction"),
        ("growth", "build_growth_strategy"),
        ("campaign", "build_campaign_plan"),
        ("marketing", "build_marketing_plan"),
        ("production", "build_production_command"),
        ("today", "build_production_command"),
        ("workflow", "build_client_workflow"),
        ("snapshot", "build_runtime_snapshot"),
        ("observability", "build_observability_report"),
        ("preview", "build_media_cache"),
        ("media cache", "build_media_cache"),
        ("trial", "build_trial_readiness_report"),
    ]
    for needle, key in mapping:
        if needle in lower:
            return key
    if category == "create":
        return "build_creative_direction"
    if category == "process":
        return "build_media_cache"
    return None


def _classify_action(action: dict[str, Any]) -> tuple[str, list[str] | None, str]:
    title = str(action.get("title") or "")
    category = str(action.get("category") or "").lower()
    combined = f"{title} {category} {action.get('client_message') or ''}".lower()
    if any(term in combined for term in BLOCKED_TERMS):
        return "blocked", None, "Blocked because it could affect external accounts, source media, or cloud/social APIs."
    if category in APPROVAL_REQUIRED_CATEGORIES:
        return "approval_required", None, "This action changes review/export/manual status and needs operator approval."
    safe_key = _title_to_safe_key(title, category)
    if safe_key and safe_key in SAFE_AUTO_COMMANDS:
        return "safe_auto", SAFE_AUTO_COMMANDS[safe_key], "Safe local rebuild or report generation."
    return "approval_required", None, "HigherKey can prepare this step, but the operator should approve it first."


def _autopilot_card(source: str, action: dict[str, Any], index: int) -> dict[str, Any]:
    safety_level, command, reason = _classify_action(action)
    action_id = _stable_id("auto", source, action.get("action_id") or action.get("title"), index)
    created_at = utc_now()
    return {
        "action_id": action_id,
        "title": str(action.get("title") or "Autopilot action"),
        "category": str(action.get("category") or "prepare"),
        "source": source,
        "safety_level": safety_level,
        "reason": reason,
        "expected_output": str(action.get("expected_impact") or action.get("client_message") or "Local project output updated."),
        "command": command,
        "linked_clip_id": action.get("linked_clip_id"),
        "linked_platform": action.get("linked_platform"),
        "approval_required": safety_level == "approval_required",
        "status": "blocked" if safety_level == "blocked" else "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "priority": int(action.get("priority") or 50),
        "client_message": str(action.get("client_message") or reason),
    }


def _default_safe_cards() -> list[dict[str, Any]]:
    defaults = [
        ("refresh_production_command", "Refresh Today’s Content Command", "build_production_command"),
        ("refresh_creative_direction", "Refresh Creative Direction", "build_creative_direction"),
        ("refresh_growth_strategy", "Refresh Growth Strategy", "build_growth_strategy"),
        ("refresh_campaign_plan", "Refresh Campaign Plan", "build_campaign_plan"),
        ("refresh_marketing_plan", "Refresh Marketing Plan", "build_marketing_plan"),
        ("refresh_client_workflow", "Refresh Client Workflow", "build_client_workflow"),
    ]
    cards: list[dict[str, Any]] = []
    now = utc_now()
    for index, (action_id, title, safe_key) in enumerate(defaults):
        cards.append({
            "action_id": action_id,
            "title": title,
            "category": "prepare",
            "source": "autopilot_default",
            "safety_level": "safe_auto",
            "reason": "Safe local rebuild or report generation.",
            "expected_output": "Updated local planning files.",
            "command": SAFE_AUTO_COMMANDS[safe_key],
            "linked_clip_id": None,
            "linked_platform": None,
            "approval_required": False,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "priority": 70 - index,
            "client_message": "HigherKey can run this locally without posting or deleting media.",
        })
    return cards


def build_autopilot_queues(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cards = [_autopilot_card("today_action_plan", action, index) for index, action in enumerate(_today_actions(data))]
    cards.extend(_default_safe_cards())
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: (item.get("safety_level") != "safe_auto", -int(item.get("priority", 0)), item.get("title", ""))):
        key = f"{card.get('title')}::{card.get('safety_level')}::{card.get('command')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)
    approval = [item for item in unique if item.get("approval_required")]
    return unique, approval


def _queue_payload(name: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "name": name,
        "actions": actions,
    }


def write_markdown(root: Path, autopilot: dict[str, Any], approval_queue: dict[str, Any], history: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    actions = autopilot.get("action_queue", {}).get("actions", [])
    approvals = approval_queue.get("actions", [])
    runs = history.get("runs", [])
    write_text(out / "operator_autopilot.md", "\n".join([
        "# Operator Autopilot",
        "",
        "HigherKey prepares local actions. You stay in control.",
        "Manual upload only. No direct posting APIs.",
        "",
        "## Queue",
        *[f"- {item['title']} [{item['safety_level']}]" for item in actions],
    ]))
    write_text(out / "autopilot_approval_queue.md", "\n".join([
        "# Autopilot Approval Queue",
        "",
        *([f"- {item['title']} - {item['reason']}" for item in approvals] or ["No approval-required actions queued."]),
    ]))
    write_text(out / "autopilot_run_history.md", "\n".join([
        "# Autopilot Run History",
        "",
        *([f"- {item.get('timestamp')} {item.get('action_id')} {item.get('status')}" for item in runs[-20:]] or ["No safe-auto runs yet."]),
    ]))
    return {
        "operator_autopilot": relative_path(out / "operator_autopilot.md", root),
        "autopilot_approval_queue": relative_path(out / "autopilot_approval_queue.md", root),
        "autopilot_run_history": relative_path(out / "autopilot_run_history.md", root),
    }


def build_operator_autopilot(root: Path, dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    data = _load_inputs(project_root)
    action_cards, approval_cards = build_autopilot_queues(data)
    history = data.get("previous_history") if isinstance(data.get("previous_history"), dict) else {}
    history = history or {"version": 1, "updated_at": utc_now(), "local_only": True, "runs": []}
    receipts = data.get("previous_receipts") if isinstance(data.get("previous_receipts"), dict) else {}
    receipts = receipts or {"version": 1, "updated_at": utc_now(), "local_only": True, "receipts": []}
    action_queue = _queue_payload("autopilot_action_queue", action_cards)
    approval_queue = _queue_payload("autopilot_approval_queue", approval_cards)
    blocked = [item for item in action_cards if item.get("safety_level") == "blocked"]
    completed_today = [item for item in safe_list(history.get("runs")) if str(item.get("timestamp", ""))[:10] == utc_now()[:10] and item.get("status") == "completed"]
    safe_ready = [item for item in action_cards if item.get("safety_level") == "safe_auto" and item.get("status") == "queued"]
    autopilot = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "status": "Ready" if safe_ready else ("Needs Approval" if approval_cards else "Idle"),
        "top_cards": {
            "safe_actions_ready": len(safe_ready),
            "awaiting_approval": len(approval_cards),
            "completed_today": len(completed_today),
            "blocked": len(blocked),
            "next_safe_run": safe_ready[0] if safe_ready else None,
            "manual_upload_reminder": "Manual upload only. No direct posting APIs.",
        },
        "action_queue": action_queue,
        "approval_queue": approval_queue,
        "run_history": history,
        "approval_receipts": receipts,
    }
    client_state = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "status": autopilot["status"],
        "message": "HigherKey can prepare safe local actions. You approve anything sensitive.",
        "safe_actions_ready": len(safe_ready),
        "awaiting_approval": len(approval_cards),
        "blocked": len(blocked),
        "next_safe_action": safe_ready[0] if safe_ready else None,
    }
    markdown = {} if dry_run else write_markdown(project_root, autopilot, approval_queue, history)
    if not dry_run:
        analytics = project_root / "analytics"
        write_json(analytics / "operator_autopilot.json", autopilot)
        write_json(analytics / "autopilot_action_queue.json", action_queue)
        write_json(analytics / "autopilot_approval_queue.json", approval_queue)
        write_json(analytics / "autopilot_run_history.json", history)
        write_json(analytics / "autopilot_approval_receipts.json", receipts)
        write_json(analytics / "client_autopilot_state.json", client_state)
    return {
        "ok": True,
        "dry_run": dry_run,
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "safe_actions_ready": len(safe_ready),
        "awaiting_approval": len(approval_cards),
        "blocked": len(blocked),
        "markdown_outputs": markdown,
    }


def _load_action_queue(root: Path) -> list[dict[str, Any]]:
    payload = load_json(root / "analytics" / "autopilot_action_queue.json", {})
    return [item for item in safe_list(payload.get("actions")) if isinstance(item, dict)]


def _history_path(root: Path) -> Path:
    return root / "analytics" / "autopilot_run_history.json"


def _receipts_path(root: Path) -> Path:
    return root / "analytics" / "autopilot_approval_receipts.json"


def _append_run(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = _history_path(root)
    payload = load_json(path, {"version": 1, "local_only": True, "runs": []})
    runs = safe_list(payload.get("runs"))
    runs.append(record)
    payload.update({"version": 1, "updated_at": utc_now(), "local_only": True, "manual_upload_only": True, "runs": runs})
    write_json(path, payload)
    return payload


def approve_action(root: Path, action_id: str, approved_by: str = "local_operator") -> dict[str, Any]:
    action = next((item for item in _load_action_queue(root) if item.get("action_id") == action_id), None)
    if not action:
        return {"ok": False, "status": "not_found", "action_id": action_id}
    timestamp = utc_now()
    receipt = {
        "receipt_id": _stable_id("receipt", action_id, timestamp),
        "action_id": action_id,
        "approved_by": approved_by,
        "approved_at": timestamp,
        "approval_scope": action.get("title"),
        "safety_note": "Approval recorded locally. No social posting or destructive action was executed.",
    }
    path = _receipts_path(root)
    payload = load_json(path, {"version": 1, "local_only": True, "receipts": []})
    receipts = safe_list(payload.get("receipts"))
    receipts.append(receipt)
    payload.update({"version": 1, "updated_at": utc_now(), "local_only": True, "manual_upload_only": True, "receipts": receipts})
    write_json(path, payload)
    try:
        write_audit_event(load_config(root), "autopilot.action_approved", source="operator_autopilot", summary={"action_id": action_id, "title": action.get("title")})
    except Exception:
        pass
    return {"ok": True, "status": "approved", "receipt": receipt}


def run_safe_actions(root: Path, *, safe_auto: bool = False, action_id: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    project_root = root.resolve()
    if not (project_root / "analytics" / "autopilot_action_queue.json").exists():
        build_operator_autopilot(project_root, dry_run=False)
    candidates = _load_action_queue(project_root)
    if action_id:
        candidates = [item for item in candidates if item.get("action_id") == action_id]
    if not safe_auto:
        return {
            "ok": True,
            "dry_run": True,
            "status": "planned",
            "message": "No actions executed. Pass --safe-auto to run safe local actions.",
            "candidate_count": len(candidates),
            "results": [],
        }
    results: list[dict[str, Any]] = []
    for action in candidates:
        command = action.get("command")
        if action.get("safety_level") != "safe_auto" or not isinstance(command, list) or command not in SAFE_AUTO_COMMANDS.values():
            results.append({"action_id": action.get("action_id"), "status": "blocked", "message": "Not a safe-auto allowlisted action."})
            continue
        if dry_run:
            results.append({"action_id": action.get("action_id"), "status": "dry_run", "command": command})
            continue
        timestamp = utc_now()
        completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, timeout=120)
        status = "completed" if completed.returncode == 0 else "failed"
        result = {
            "action_id": action.get("action_id"),
            "title": action.get("title"),
            "timestamp": timestamp,
            "status": status,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1200:],
            "stderr_tail": completed.stderr[-1200:],
            "local_only": True,
        }
        _append_run(project_root, result)
        try:
            write_audit_event(load_config(project_root), "autopilot.safe_action_run", severity="info" if status == "completed" else "fail", source="operator_autopilot", summary={"action_id": action.get("action_id"), "status": status})
        except Exception:
            pass
        results.append(result)
    return {
        "ok": all(item.get("status") in {"completed", "dry_run"} for item in results),
        "dry_run": dry_run,
        "safe_auto": safe_auto,
        "status": "completed" if results else "empty",
        "results": results,
        "local_only": True,
        "manual_upload_only": True,
    }
