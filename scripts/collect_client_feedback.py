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


def collect_feedback(root: Path, args: argparse.Namespace) -> dict[str, object]:
    output = root / "analytics" / "client_feedback.json"
    payload = feedback_payload(args)
    result = {
        "status": "pass",
        "dry_run": bool(args.dry_run),
        "output": str(output),
        "fields": sorted(payload.keys()),
        "local_only": True,
    }
    if args.dry_run:
        result["preview"] = payload
        return result
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["feedback"] = payload
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture client beta feedback locally.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--dry-run", action="store_true", help="Show the feedback schema without writing.")
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
    print(json.dumps(collect_feedback(root, args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
