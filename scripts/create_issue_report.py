#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEYS = {"token", "secret", "password", "auth", "authorization"}
MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v"}
FORBIDDEN_REPORT_NAMES = {"runtime_state.db", "events.jsonl", "audit_log.jsonl", "higherkey-local-api-token.txt"}
FORBIDDEN_REPORT_DIRS = {"content_inbox", "clips", "captions", "social_exports", "approved_posts", "media_cache"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def redact(value: object) -> object:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in SENSITIVE_KEYS):
                result[key] = "[redacted]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def redact_paths(value: object, root: Path) -> object:
    root_text = str(root)
    home_text = str(Path.home())
    if isinstance(value, dict):
        return {key: redact_paths(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_paths(item, root) for item in value]
    if isinstance(value, str):
        text = value.replace(root_text, "[project_root]").replace(home_text, "[home]")
        return re.sub(r"/Volumes/[^\\s\"']+", "[external_volume_path]", text)
    return value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def issue_report(
    root: Path,
    output: Path,
    dry_run: bool = False,
    include_logs: bool = False,
    include_runtime: bool = False,
    redact_path_values: bool = True,
    client_safe: bool = True,
) -> dict[str, object]:
    output = output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()

    analytics = root / "analytics"
    source_files = {
        "diagnostics_summary.json": analytics / "diagnostics.json",
        "client_state.json": analytics / "client_state.json",
        "client_workflow.json": analytics / "client_workflow.json",
        "client_tasks.json": analytics / "client_tasks.json",
        "client_integrity.json": analytics / "client_integrity.json",
        "client_storage.json": analytics / "client_storage.json",
        "client_feedback_summary.json": analytics / "client_feedback_summary.json",
        "client_issue_queue.json": analytics / "client_issue_queue.json",
        "client_trial_status.json": analytics / "client_trial_status.json",
        "feedback_triage_report.json": analytics / "feedback_triage_report.json",
        "client_patch_plan.json": analytics / "client_patch_plan.json",
        "client_response_notes.json": analytics / "client_response_notes.json",
        "trial_fix_backlog.json": analytics / "trial_fix_backlog.json",
        "trial_risk_summary.json": analytics / "trial_risk_summary.json",
        "client_delivery_manifest.json": analytics / "client_delivery_manifest.json",
    }
    if include_runtime:
        source_files.update({
            "runtime_snapshot.json": analytics / "runtime_snapshot.json",
            "client_metrics.json": analytics / "client_metrics.json",
            "client_observability.json": analytics / "client_observability.json",
        })
    if include_logs and not client_safe:
        source_files.update({
            "qa_report.json": analytics / "qa_report.json",
            "project_repair_report.json": analytics / "project_repair_report.json",
        })
    included = [name for name, source in source_files.items() if source.exists()]
    missing = [name for name, source in source_files.items() if not source.exists()]
    forbidden = []
    forbidden_roots = [
        root / "content_inbox",
        root / "clips",
        root / "captions",
        root / "out" / "social_exports",
        root / "out" / "approved_posts",
        root / "out" / "media_cache",
        root / "analytics" / "runtime_state.db",
    ]
    for folder in forbidden_roots:
        if output == folder or folder in output.parents:
            forbidden.append(str(folder))
    summary = {
        "created_at": utc_now(),
        "product": "HigherKey Operator OS",
        "local_only": True,
        "client_safe": client_safe,
        "redact_paths": redact_path_values,
        "includes_original_footage": False,
        "includes_private_media": False,
        "includes_runtime_db": False,
        "includes_content_inbox": False,
        "includes_clips": False,
        "includes_captions": False,
        "includes_social_exports": False,
        "includes_tokens": False,
        "include_logs_requested": include_logs,
        "include_runtime_requested": include_runtime,
        "included_files": included,
        "missing_optional_files": missing,
        "forbidden_output_targets": forbidden,
        "support_note": "This package is safe to share for support. It excludes source footage, generated clips, large logs, runtime DB files, and local tokens by default.",
    }
    text = "\n".join([
        "HigherKey Operator OS Client Issue Report",
        f"Created: {summary['created_at']}",
        "",
        "Included:",
        *[f"- {name}" for name in included],
        "",
        "Not included by default:",
        "- Original footage",
        "- Private generated media",
        "- Full logs",
        "- Runtime database",
        "- Local tokens or secrets",
        "",
        "Client note:",
        "Describe what happened, what you expected, and which step you were on.",
        "Feedback and issue queue summaries are redacted before inclusion.",
        "",
    ])

    status = "fail" if forbidden else "pass"
    if not dry_run and not forbidden:
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "issue_report.json", summary)
        (output / "issue_report.txt").write_text(text, encoding="utf-8")
        for name, source in source_files.items():
            if source.exists():
                payload = redact(load_json(source, {}))
                if redact_path_values:
                    payload = redact_paths(payload, root)
                write_json(output / name, payload)

    output_forbidden = []
    if output.exists():
        for path in output.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.relative_to(output).parts)
            if path.name in FORBIDDEN_REPORT_NAMES or parts.intersection(FORBIDDEN_REPORT_DIRS) or path.suffix.lower() in MEDIA_EXTENSIONS:
                output_forbidden.append(str(path.relative_to(output)))

    return {
        "status": status,
        "dry_run": dry_run,
        "output": str(output),
        "included": ["issue_report.json", "issue_report.txt", *included],
        "missing_optional_files": missing,
        "local_only": True,
        "client_safe": client_safe,
        "redact_paths": redact_path_values,
        "forbidden_output_targets": forbidden,
        "forbidden_in_report": output_forbidden,
        "private_media_included": False,
        "source_media_included": False,
        "social_exports_included": False,
        "runtime_db_included": False,
        "tokens_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a client-safe local issue report package.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--output", default="out/client_issue_report", help="Output folder.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned report contents without writing.")
    parser.add_argument("--include-logs", action="store_true", help="Include extra JSON summaries. Full logs remain excluded unless client-safe is disabled.")
    parser.add_argument("--include-runtime", action="store_true", help="Include client-safe runtime snapshots, not runtime DB files.")
    parser.add_argument("--redact-paths", dest="redact_paths", action="store_true", default=True, help="Redact absolute local paths in copied JSON.")
    parser.add_argument("--no-redact-paths", dest="redact_paths", action="store_false", help="Keep absolute paths in copied JSON.")
    parser.add_argument("--client-safe", dest="client_safe", action="store_true", default=True, help="Exclude private media, full logs, runtime DB files, and local tokens.")
    parser.add_argument("--no-client-safe", dest="client_safe", action="store_false", help="Allow extra diagnostic summaries when explicitly requested.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = issue_report(
        root,
        Path(args.output),
        dry_run=args.dry_run,
        include_logs=args.include_logs,
        include_runtime=args.include_runtime,
        redact_path_values=args.redact_paths,
        client_safe=args.client_safe,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
