#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def feedback_payload(args: argparse.Namespace) -> dict[str, object]:
    return {
        "client_name": args.client_name or "",
        "session_date": args.session_date or utc_now(),
        "what_worked": args.what_worked or "",
        "what_confused_you": args.what_confused_you or "",
        "bugs_seen": args.bugs_seen or "",
        "feature_requests": args.feature_requests or "",
        "upload_workflow_rating": args.upload_workflow_rating,
        "overall_rating": args.overall_rating,
        "notes": args.notes or "",
        "local_only": True,
        "cloud_submission": False,
        "updated_at": utc_now(),
    }


def feedback_template() -> dict[str, object]:
    return {
        "client_name": "",
        "session_date": "",
        "what_worked": "",
        "what_confused_you": "",
        "bugs_seen": "",
        "feature_requests": "",
        "upload_workflow_rating": "",
        "overall_rating": "",
        "notes": "",
        "local_only": True,
        "cloud_submission": False,
    }


def prompt_if_needed(args: argparse.Namespace) -> argparse.Namespace:
    if not args.interactive:
        return args
    prompts = [
        ("client_name", "Client name (optional)"),
        ("what_worked", "What worked well"),
        ("what_confused_you", "What was confusing"),
        ("bugs_seen", "Bugs seen"),
        ("feature_requests", "Feature requests"),
        ("upload_workflow_rating", "Upload workflow rating"),
        ("overall_rating", "Overall rating"),
        ("notes", "Additional notes"),
    ]
    for key, label in prompts:
        if getattr(args, key):
            continue
        try:
            setattr(args, key, input(f"{label}: ").strip())
        except EOFError:
            setattr(args, key, "")
    return args


def summarize_feedback(payload: dict[str, object]) -> dict[str, object]:
    filled = [key for key, value in payload.items() if value not in ("", None, [], {})]
    return {
        "status": "pass",
        "local_only": True,
        "updated_at": utc_now(),
        "client_name_present": bool(payload.get("client_name")),
        "session_date": payload.get("session_date"),
        "fields_completed": len(filled),
        "overall_rating": payload.get("overall_rating"),
        "upload_workflow_rating": payload.get("upload_workflow_rating"),
        "has_bugs": bool(payload.get("bugs_seen")),
        "has_feature_requests": bool(payload.get("feature_requests")),
        "next_action": "Review feedback locally and update the trial notes.",
    }


def collect_feedback(root: Path, args: argparse.Namespace) -> dict[str, object]:
    output = root / "analytics" / "client_feedback.json"
    summary_output = root / "analytics" / "client_feedback_summary.json"
    if args.template:
        result = {
            "status": "pass",
            "template": feedback_template(),
            "local_only": True,
            "output": str(output),
            "summary_output": str(summary_output),
        }
        if not args.dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(feedback_template(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            summary_output.write_text(json.dumps(summarize_feedback(feedback_template()), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result
    if args.export_summary:
        existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else feedback_template()
        summary = summarize_feedback(existing)
        if not args.dry_run:
            summary_output.parent.mkdir(parents=True, exist_ok=True)
            summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"status": "pass", "dry_run": bool(args.dry_run), "output": str(summary_output), "summary": summary, "local_only": True}
    args = prompt_if_needed(args)
    payload = feedback_payload(args)
    summary = summarize_feedback(payload)
    result = {
        "status": "pass",
        "dry_run": bool(args.dry_run),
        "output": str(output),
        "summary_output": str(summary_output),
        "fields": sorted(payload.keys()),
        "local_only": True,
    }
    if args.dry_run:
        result["preview"] = payload
        result["summary"] = summary
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["feedback"] = payload
    result["summary"] = summary
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture client beta feedback locally.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--dry-run", action="store_true", help="Show the feedback schema without writing.")
    parser.add_argument("--interactive", action="store_true", help="Prompt locally for feedback fields.")
    parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--template", action="store_true", help="Emit or write a blank feedback template.")
    parser.add_argument("--export-summary", action="store_true", help="Build analytics/client_feedback_summary.json from existing feedback.")
    parser.add_argument("--client-name", default="")
    parser.add_argument("--session-date", default="")
    parser.add_argument("--what-worked", default="")
    parser.add_argument("--what-confused-you", default="")
    parser.add_argument("--bugs-seen", default="")
    parser.add_argument("--feature-requests", default="")
    parser.add_argument("--upload-workflow-rating", default="")
    parser.add_argument("--overall-rating", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    indent = None if args.json else 2
    print(json.dumps(collect_feedback(root, args), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
