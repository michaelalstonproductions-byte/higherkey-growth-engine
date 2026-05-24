#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.client_feedback import collect_feedback, create_feedback_template
from growth_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect local client trial feedback without cloud APIs.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--template", action="store_true", help="Create a local feedback template.")
    parser.add_argument("--input", dest="input_path", help="Import local JSON or Markdown feedback from inside the project.")
    parser.add_argument("--category", default="other", help="Feedback category.")
    parser.add_argument("--severity", default="medium", help="Feedback severity.")
    parser.add_argument("--title", default="", help="Feedback title.")
    parser.add_argument("--description", default="", help="Feedback description.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write feedback outputs.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    if args.template or not any([args.input_path, args.title, args.description]):
        result = create_feedback_template(config, dry_run=args.dry_run)
    else:
        result = collect_feedback(
            config,
            input_path=Path(args.input_path) if args.input_path else None,
            category=args.category,
            severity=args.severity,
            title=args.title,
            description=args.description,
            dry_run=args.dry_run,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "ready", "needs_attention"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
