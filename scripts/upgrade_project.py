#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.migrations import apply_upgrade, build_upgrade_plan, pre_upgrade_backup_manifest, rollback_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Check, plan, or apply HigherKey local project upgrades.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--check", action="store_true", help="Check whether upgrade work is required.")
    parser.add_argument("--plan", action="store_true", help="Build upgrade plan without applying migrations.")
    parser.add_argument("--apply", action="store_true", help="Apply safe migrations.")
    parser.add_argument("--rollback-plan", action="store_true", help="Write rollback plan only.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--force", action="store_true", help="Allow apply despite blockers after review.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    if args.apply:
        payload = apply_upgrade(config, force=args.force)
    else:
        plan = build_upgrade_plan(config)
        pre_upgrade_backup_manifest(config)
        rollback = rollback_plan(config, plan, applied=False)
        payload = {"status": plan["status"], "upgrade_plan": plan, "rollback_plan": rollback, "local_only": True}
        if args.check:
            payload["mode"] = "check"
        elif args.rollback_plan:
            payload["mode"] = "rollback-plan"
        else:
            payload["mode"] = "plan"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
