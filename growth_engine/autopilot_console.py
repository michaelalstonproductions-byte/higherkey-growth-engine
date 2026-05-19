from __future__ import annotations

from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .marketing_intelligence import load_json, safe_list, write_json, write_text


def _load_inputs(root: Path) -> dict[str, Any]:
    analytics = root / "analytics"
    return {
        "operator_autopilot": load_json(analytics / "operator_autopilot.json", {}),
        "action_queue": load_json(analytics / "autopilot_action_queue.json", {}),
        "approval_queue": load_json(analytics / "autopilot_approval_queue.json", {}),
        "run_history": load_json(analytics / "autopilot_run_history.json", {}),
        "approval_receipts": load_json(analytics / "autopilot_approval_receipts.json", {}),
        "client_state": load_json(analytics / "client_autopilot_state.json", {}),
        "safety_report": load_json(analytics / "autopilot_safety_report.json", {}),
        "policy": load_json(root / "config" / "autopilot_policy.json", {}),
    }


def _actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("action_queue") if isinstance(data.get("action_queue"), dict) else {}
    actions = payload.get("actions") if isinstance(payload, dict) else []
    return [item for item in safe_list(actions) if isinstance(item, dict)]


def _approval_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("approval_queue") if isinstance(data.get("approval_queue"), dict) else {}
    actions = payload.get("actions") if isinstance(payload, dict) else []
    return [item for item in safe_list(actions) if isinstance(item, dict)]


def _runs(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("run_history") if isinstance(data.get("run_history"), dict) else {}
    runs = payload.get("runs") if isinstance(payload, dict) else []
    return [item for item in safe_list(runs) if isinstance(item, dict)]


def _receipts(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("approval_receipts") if isinstance(data.get("approval_receipts"), dict) else {}
    receipts = payload.get("receipts") if isinstance(payload, dict) else []
    return [item for item in safe_list(receipts) if isinstance(item, dict)]


def _today_prefix() -> str:
    return utc_now()[:10]


def _tail_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "No output captured."
    return text.replace("\n", " ")[-220:]


def build_queue_summary(actions: list[dict[str, Any]], runs: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> dict[str, int]:
    today = _today_prefix()
    return {
        "queued": len([item for item in actions if item.get("status") == "queued"]),
        "safe_auto": len([item for item in actions if item.get("safety_level") == "safe_auto"]),
        "awaiting_approval": len(approvals),
        "blocked": len([item for item in actions if item.get("safety_level") == "blocked" or item.get("status") == "blocked"]),
        "running": len([item for item in runs if item.get("status") == "running"]),
        "completed": len([item for item in runs if item.get("status") == "completed" and str(item.get("completed_at") or item.get("timestamp") or "").startswith(today)]),
        "failed": len([item for item in runs if item.get("status") == "failed"]),
    }


def build_recent_runs(actions: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item.get("action_id"): item for item in actions if item.get("action_id")}
    recent: list[dict[str, Any]] = []
    for run in runs[-20:]:
        action = by_id.get(run.get("action_id"), {})
        status = str(run.get("status") or "recorded")
        safety = str(run.get("safety_level") or action.get("safety_level") or "")
        retry_available = status == "failed" and safety == "safe_auto"
        recent.append({
            "run_id": run.get("run_id"),
            "action_id": run.get("action_id"),
            "title": run.get("title") or action.get("title") or run.get("action_id") or "Autopilot run",
            "status": status,
            "dry_run": bool(run.get("dry_run")),
            "safety_level": safety,
            "command": run.get("command") or action.get("command"),
            "started_at": run.get("started_at") or run.get("timestamp"),
            "completed_at": run.get("completed_at"),
            "return_code": run.get("return_code"),
            "output_summary": _tail_summary(run.get("stderr_tail") if status == "failed" else run.get("stdout_tail")),
            "retry_available": retry_available,
            "client_message": "Retry is available as a dry-run plan." if retry_available else "Run recorded locally.",
        })
    return list(reversed(recent))


def build_approval_summary(approvals: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    latest = receipts[-1] if receipts else None
    return {
        "approval_required_count": len(approvals),
        "approved_count": len(receipts),
        "expired_count": 0,
        "latest_receipt": latest,
    }


def build_safety_summary(data: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    report = data.get("safety_report") if isinstance(data.get("safety_report"), dict) else {}
    return {
        "policy_status": "pass" if policy else "missing",
        "local_only": bool(policy.get("local_only", True)),
        "manual_upload_only": bool(policy.get("manual_upload_only", True)),
        "social_posting_allowed": bool(policy.get("social_posting_allowed", False)),
        "cloud_apis_allowed": bool(policy.get("cloud_apis_allowed", False)),
        "preflight_status": report.get("status") or "not_run",
        "blocked_reason_count": len([item for item in actions if item.get("safety_level") == "blocked" or item.get("status") == "blocked"]),
    }


def build_autopilot_console(root: Path, dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    data = _load_inputs(project_root)
    actions = _actions(data)
    approvals = _approval_actions(data)
    runs = _runs(data)
    receipts = _receipts(data)
    queue_summary = build_queue_summary(actions, runs, approvals)
    recent_runs = build_recent_runs(actions, runs)
    approval_summary = build_approval_summary(approvals, receipts)
    safety_summary = build_safety_summary(data, actions)
    failed_retryable = [item for item in recent_runs if item.get("retry_available")]
    console = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "status": "Ready" if safety_summary["preflight_status"] in {"pass", "not_run"} else "Needs Attention",
        "queue_summary": queue_summary,
        "recent_runs": recent_runs,
        "approval_summary": approval_summary,
        "safety_summary": safety_summary,
        "failed_retryable": failed_retryable,
        "output_summary": {
            "latest_run": recent_runs[0] if recent_runs else None,
            "latest_message": recent_runs[0]["client_message"] if recent_runs else "No autopilot runs recorded yet.",
        },
    }
    run_console = {
        "version": 1,
        "updated_at": console["updated_at"],
        "local_only": True,
        "manual_upload_only": True,
        "queue": actions,
        "recent_runs": recent_runs,
        "failed_retryable": failed_retryable,
        "approval_queue": approvals,
        "safety_preflight": safety_summary,
    }
    run_summary = {
        "version": 1,
        "updated_at": console["updated_at"],
        "local_only": True,
        "manual_upload_only": True,
        "queue_summary": queue_summary,
        "latest_run": recent_runs[0] if recent_runs else None,
        "retryable_failed_count": len(failed_retryable),
    }
    client_console = {
        "version": 1,
        "updated_at": console["updated_at"],
        "local_only": True,
        "manual_upload_only": True,
        "status": console["status"],
        "message": "HigherKey can run safe local preparation tasks. You approve sensitive actions. Manual upload only.",
        "safe_actions_ready": queue_summary["safe_auto"],
        "awaiting_approval": queue_summary["awaiting_approval"],
        "failed": queue_summary["failed"],
        "preflight_status": safety_summary["preflight_status"],
        "latest_run": recent_runs[0] if recent_runs else None,
    }
    markdown = {} if dry_run else write_console_markdown(project_root, console, run_console, run_summary)
    if not dry_run:
        analytics = project_root / "analytics"
        write_json(analytics / "autopilot_console.json", console)
        write_json(analytics / "autopilot_run_console.json", run_console)
        write_json(analytics / "autopilot_run_summary.json", run_summary)
        write_json(analytics / "client_autopilot_console.json", client_console)
    return {
        "ok": True,
        "dry_run": dry_run,
        "status": console["status"],
        "local_only": True,
        "manual_upload_only": True,
        "queue_summary": queue_summary,
        "safety_summary": safety_summary,
        "markdown_outputs": markdown,
    }


def write_console_markdown(root: Path, console: dict[str, Any], run_console: dict[str, Any], run_summary: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    queue = run_console.get("queue", [])
    recent = run_console.get("recent_runs", [])
    safety = console.get("safety_summary", {})
    write_text(out / "autopilot_console.md", "\n".join([
        "# Autopilot Run Console",
        "",
        "HigherKey can run safe local preparation tasks. You approve sensitive actions. Manual upload only.",
        "",
        "## Queue Summary",
        *[f"- {key}: {value}" for key, value in console.get("queue_summary", {}).items()],
        "",
        "## Run Queue",
        *([f"- {item.get('title')} [{item.get('safety_level')}] - {item.get('status')}" for item in queue[:20]] or ["No queued actions."]),
    ]))
    write_text(out / "autopilot_run_summary.md", "\n".join([
        "# Autopilot Run Summary",
        "",
        *([f"- {item.get('title')} - {item.get('status')} - {item.get('output_summary')}" for item in recent[:20]] or ["No recent runs."]),
        "",
        f"Retryable failed actions: {run_summary.get('retryable_failed_count', 0)}",
    ]))
    write_text(out / "autopilot_safety_summary.md", "\n".join([
        "# Autopilot Safety Summary",
        "",
        *[f"- {key}: {value}" for key, value in safety.items()],
    ]))
    return {
        "autopilot_console": relative_path(out / "autopilot_console.md", root),
        "autopilot_run_summary": relative_path(out / "autopilot_run_summary.md", root),
        "autopilot_safety_summary": relative_path(out / "autopilot_safety_summary.md", root),
    }
