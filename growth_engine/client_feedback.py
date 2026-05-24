from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


CATEGORIES = {
    "bug",
    "confusion",
    "feature_request",
    "onboarding",
    "import_issue",
    "export_issue",
    "editor_issue",
    "social_connector_issue",
    "delivery_issue",
    "performance",
    "other",
}
SEVERITIES = {"blocker", "high", "medium", "low"}
STATUSES = {"new", "triaged", "in_progress", "fixed", "needs_client_info", "closed"}
SENSITIVE_KEY_RE = re.compile(r"(token|secret|password|credential|authorization|bearer)", re.IGNORECASE)
TOKEN_RE = re.compile(r"(bearer\s+[a-z0-9._-]+|[a-z0-9._-]{32,})", re.IGNORECASE)


def _load(path: Path, fallback: Any) -> Any:
    return load_json_file(path, fallback)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def redact_text(value: str, root: Path) -> str:
    text = str(value)
    text = text.replace(str(root), "[project_root]").replace(str(Path.home()), "[home]")
    text = re.sub(r"/Volumes/[^\s\"']+", "[external_volume_path]", text)
    text = TOKEN_RE.sub("[redacted]", text)
    return text


def redact_value(value: Any, root: Path) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                out[key] = "[redacted]"
            else:
                out[key] = redact_value(item, root)
        return out
    if isinstance(value, list):
        return [redact_value(item, root) for item in value]
    if isinstance(value, str):
        return redact_text(value, root)
    return value


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_category(value: str | None) -> str:
    text = (value or "other").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in CATEGORIES else "other"


def _normalize_severity(value: str | None) -> str:
    text = (value or "medium").strip().lower()
    return text if text in SEVERITIES else "medium"


def _normalize_status(value: str | None) -> str:
    text = (value or "new").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in STATUSES else "new"


def _feedback_item(raw: dict[str, Any], root: Path, source: str) -> dict[str, Any]:
    title = redact_text(str(raw.get("title") or "Client feedback"), root).strip()[:160]
    description = redact_text(str(raw.get("description") or raw.get("body") or raw.get("note") or ""), root).strip()
    category = _normalize_category(str(raw.get("category") or "other"))
    severity = _normalize_severity(str(raw.get("severity") or "medium"))
    status = _normalize_status(str(raw.get("status") or "new"))
    now = utc_now()
    feedback_id = str(raw.get("feedback_id") or _stable_id(source, title, description, category))
    related_file = raw.get("related_file")
    return {
        "feedback_id": feedback_id,
        "source": redact_text(str(raw.get("source") or source), root),
        "category": category,
        "severity": severity,
        "title": title or "Client feedback",
        "description": description,
        "client_message": redact_text(str(raw.get("client_message") or description or title), root),
        "internal_notes": redact_text(str(raw.get("internal_notes") or raw.get("notes") or ""), root),
        "related_page": redact_text(str(raw.get("related_page") or ""), root),
        "related_action": redact_text(str(raw.get("related_action") or ""), root),
        "related_file": redact_text(str(related_file), root) if related_file else "",
        "status": status,
        "created_at": str(raw.get("created_at") or now),
        "updated_at": now,
    }


def _items_from_markdown(path: Path, root: Path) -> list[dict[str, Any]]:
    text = redact_text(path.read_text(encoding="utf-8"), root)
    title = path.stem.replace("_", " ").replace("-", " ").title()
    category = "other"
    severity = "medium"
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "category":
            category = value.strip()
        if key.strip().lower() == "severity":
            severity = value.strip()
        if key.strip().lower() == "title" and value.strip():
            title = value.strip()
    return [_feedback_item({
        "source": f"markdown:{path.name}",
        "category": category,
        "severity": severity,
        "title": title,
        "description": text,
    }, root, f"markdown:{path.name}")]


def _items_from_json(path: Path, root: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items: list[Any]
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("feedback") or payload.get("items") or [payload]
    else:
        raw_items = []
    return [_feedback_item(item, root, f"json:{path.name}") for item in raw_items if isinstance(item, dict)]


def load_feedback_inbox(config: AppConfig) -> dict[str, Any]:
    payload = _load(config.analytics_dir / "client_feedback_inbox.json", {})
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload
    return {"version": 1, "updated_at": utc_now(), "items": []}


def summarize_feedback(config: AppConfig, items: list[dict[str, Any]]) -> dict[str, Any]:
    by_category = Counter(item.get("category") or "other" for item in items)
    by_severity = Counter(item.get("severity") or "medium" for item in items)
    by_status = Counter(item.get("status") or "new" for item in items)
    blockers = [item for item in items if item.get("severity") == "blocker" and item.get("status") not in {"fixed", "closed"}]
    high = [item for item in items if item.get("severity") == "high" and item.get("status") not in {"fixed", "closed"}]
    needs_client_info = [item for item in items if item.get("status") == "needs_client_info"]
    qa_report = _load(config.analytics_dir / "qa_report.json", {})
    rehearsal = _load(config.analytics_dir / "client_rehearsal_report.json", {})
    launch = _load(config.analytics_dir / "client_launch_readiness.json", {})
    return {
        "version": 1,
        "updated_at": utc_now(),
        "status": "needs_attention" if blockers or high or qa_report.get("status") == "fail" else "ready",
        "total": len(items),
        "by_category": dict(sorted(by_category.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "by_status": dict(sorted(by_status.items())),
        "blocker_count": len(blockers),
        "high_count": len(high),
        "needs_client_info_count": len(needs_client_info),
        "qa_status": qa_report.get("status"),
        "client_rehearsal_status": rehearsal.get("status"),
        "launch_readiness_status": launch.get("status"),
        "local_only": True,
        "redacted": True,
        "private_media_included": False,
        "tokens_included": False,
    }


def write_feedback_state(config: AppConfig, items: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
    now = utc_now()
    inbox = {
        "version": 1,
        "updated_at": now,
        "local_only": True,
        "redacted": True,
        "items": sorted(items, key=lambda item: (item.get("severity") != "blocker", item.get("created_at", ""))),
    }
    summary = summarize_feedback(config, inbox["items"])
    trial_status = {
        "version": 1,
        "updated_at": now,
        "status": summary["status"],
        "blockers": summary["blocker_count"],
        "high_priority": summary["high_count"],
        "needs_client_info": summary["needs_client_info_count"],
        "feedback_total": summary["total"],
        "next_action": "Build Issue Queue" if summary["status"] == "needs_attention" else "Continue client rehearsal",
        "client_message": "Feedback is stored locally. Support packages are redacted and exclude private media by default.",
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "client_feedback_inbox.json", inbox)
        save_json_file(config.analytics_dir / "client_feedback_summary.json", summary)
        save_json_file(config.analytics_dir / "client_trial_status.json", trial_status)
    return {"inbox": inbox, "summary": summary, "trial_status": trial_status}


def create_feedback_template(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    template = {
        "feedback": [
            {
                "category": "confusion",
                "severity": "medium",
                "title": "What happened?",
                "description": "Describe what you expected and what happened.",
                "related_page": "Launch, Review, Editor, Delivery, Scheduler, or Support",
                "related_action": "Button or step name",
                "status": "new",
            }
        ]
    }
    md = "\n".join([
        "# HigherKey Trial Feedback",
        "",
        "Feedback is stored locally. Do not paste tokens, passwords, private URLs, or source media paths.",
        "",
        "Title:",
        "Category: confusion",
        "Severity: medium",
        "Related Page:",
        "Related Action:",
        "",
        "Description:",
        "",
    ])
    if not dry_run:
        save_json_file(config.root / "out" / "client_delivery" / "trial_feedback_template.json", template)
        _write_text(config.root / "out" / "client_delivery" / "TRIAL_FEEDBACK_TEMPLATE.md", md)
        current = load_feedback_inbox(config)
        write_feedback_state(config, list(current.get("items", [])), dry_run=False)
    return {
        "status": "pass",
        "template_json": "out/client_delivery/trial_feedback_template.json",
        "template_markdown": "out/client_delivery/TRIAL_FEEDBACK_TEMPLATE.md",
        "dry_run": dry_run,
    }


def collect_feedback(
    config: AppConfig,
    *,
    input_path: Path | None = None,
    category: str | None = None,
    severity: str | None = None,
    title: str | None = None,
    description: str | None = None,
    source: str = "operator_entry",
    dry_run: bool = False,
) -> dict[str, Any]:
    current = load_feedback_inbox(config)
    items = list(current.get("items", []))
    imported: list[dict[str, Any]] = []
    if input_path:
        path = input_path.expanduser()
        if not path.is_absolute():
            path = config.root / path
        path = path.resolve()
        try:
            path.relative_to(config.root.resolve())
        except ValueError:
            return {"status": "fail", "reason": "input_outside_project_root", "path": str(path)}
        if not path.exists():
            return {"status": "fail", "reason": "input_missing", "path": relative_path(path, config.root)}
        if path.suffix.lower() == ".json":
            imported = _items_from_json(path, config.root)
        elif path.suffix.lower() in {".md", ".txt"}:
            imported = _items_from_markdown(path, config.root)
        else:
            return {"status": "fail", "reason": "unsupported_input_type", "path": relative_path(path, config.root)}
    elif title or description:
        imported = [_feedback_item({
            "source": source,
            "category": category or "other",
            "severity": severity or "medium",
            "title": title or "Client feedback",
            "description": description or "",
        }, config.root, source)]
    seen = {item.get("feedback_id") for item in items}
    for item in imported:
        if item.get("feedback_id") not in seen:
            items.append(item)
            seen.add(item.get("feedback_id"))
    state = write_feedback_state(config, items, dry_run=dry_run)
    return {
        "status": "pass",
        "imported": len(imported),
        "total": len(items),
        "dry_run": dry_run,
        "summary": state["summary"],
    }


def build_issue_queue(config: AppConfig, *, dry_run: bool = False) -> dict[str, Any]:
    inbox = load_feedback_inbox(config)
    items = list(inbox.get("items", []))
    summary = summarize_feedback(config, items)
    qa = _load(config.analytics_dir / "qa_report.json", {})
    rehearsal = _load(config.analytics_dir / "client_rehearsal_report.json", {})
    launch = _load(config.analytics_dir / "client_launch_readiness.json", {})
    issues: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("status") in {"fixed", "closed"}:
            continue
        grouped[(str(item.get("severity") or "medium"), str(item.get("category") or "other"))].append(item)
    priority = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    for (severity, category), group in sorted(grouped.items(), key=lambda pair: (priority.get(pair[0][0], 9), pair[0][1])):
        issue_id = "issue_" + _stable_id(severity, category, len(group), ",".join(item.get("feedback_id", "") for item in group))
        issues.append({
            "issue_id": issue_id,
            "severity": severity,
            "category": category,
            "status": "new" if any(item.get("status") == "new" for item in group) else "triaged",
            "title": f"{len(group)} {category.replace('_', ' ')} item(s)",
            "feedback_ids": [item.get("feedback_id") for item in group],
            "client_messages": [item.get("client_message") for item in group[:5]],
            "repeated": len(group) > 1,
            "next_action": "Triage before next client session" if severity in {"blocker", "high"} else "Review during support pass",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })
    if qa.get("status") == "fail":
        issues.append({
            "issue_id": "issue_qa_failure",
            "severity": "blocker",
            "category": "bug",
            "status": "new",
            "title": "QA failure must be reviewed",
            "feedback_ids": [],
            "client_messages": ["QA reported a failure."],
            "repeated": False,
            "next_action": "Run QA and inspect analytics/qa_report.json",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })
    queue = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "needs_attention" if any(issue["severity"] in {"blocker", "high"} for issue in issues) else "ready",
        "local_only": True,
        "redacted": True,
        "issues": issues,
        "summary": summary,
        "qa_status": qa.get("status"),
        "client_rehearsal_status": rehearsal.get("status"),
        "launch_readiness_status": launch.get("status"),
    }
    trial_status = {
        "version": 1,
        "updated_at": queue["updated_at"],
        "status": queue["status"],
        "issue_count": len(issues),
        "blocker_count": len([issue for issue in issues if issue["severity"] == "blocker"]),
        "high_count": len([issue for issue in issues if issue["severity"] == "high"]),
        "next_action": "Resolve blockers before client handoff" if queue["status"] == "needs_attention" else "Ready for next client trial",
        "client_message": "Feedback is stored locally. Support packages are redacted and exclude private media by default.",
    }
    if not dry_run:
        save_json_file(config.analytics_dir / "client_issue_queue.json", queue)
        save_json_file(config.analytics_dir / "client_trial_status.json", trial_status)
        _write_issue_docs(config, queue, trial_status)
    return {"status": queue["status"], "issue_count": len(issues), "queue": queue, "trial_status": trial_status, "dry_run": dry_run}


def _write_issue_docs(config: AppConfig, queue: dict[str, Any], trial_status: dict[str, Any]) -> None:
    out = config.root / "out" / "client_delivery"
    issue_lines = [
        "# Trial Issue Queue",
        "",
        "Feedback is stored locally. Support packages are redacted and exclude private media by default.",
        "",
        f"Status: {queue.get('status')}",
        "",
    ]
    for issue in queue.get("issues", []):
        issue_lines.extend([
            f"## {issue.get('title')}",
            f"- Severity: {issue.get('severity')}",
            f"- Category: {issue.get('category')}",
            f"- Next action: {issue.get('next_action')}",
            "",
        ])
    if not queue.get("issues"):
        issue_lines.append("No open client trial issues are queued.")
    _write_text(out / "TRIAL_ISSUE_QUEUE.md", "\n".join(issue_lines))
    plan_lines = [
        "# Trial Fix Plan",
        "",
        f"Trial status: {trial_status.get('status')}",
        "",
        "1. Resolve blocker and high-priority feedback first.",
        "2. Re-run client rehearsal and launch audit.",
        "3. Create a client-safe support package if more context is needed.",
        "4. Keep original media, tokens, local connector config, logs, and runtime DB files out of shared packages.",
        "",
    ]
    _write_text(out / "TRIAL_FIX_PLAN.md", "\n".join(plan_lines))
