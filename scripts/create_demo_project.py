#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

FOLDERS = ("content_inbox", "clips", "captions", "queue", "analytics", "out", "logs", "config")


def build_readme(project_name: str) -> str:
    return f"""# {project_name} Demo Project

Start here:

1. Open HigherKey Operator OS.
2. Select this folder as the active project.
3. Click Import Footage and choose MP4, MOV, or M4V files.
4. Click Process Media.
5. Review clips, approve the best ones, and export social packs.
6. Upload manually from out/social_exports/.

HigherKey runs locally. No cloud APIs, social APIs, or direct posting are configured.
"""


def create_demo_project(target: Path, dry_run: bool = False, include_sample_instructions: bool = True) -> dict[str, object]:
    target = target.expanduser().resolve()
    project_name = target.name or "HigherKey Demo Project"
    planned = [str(target / folder) for folder in FOLDERS]
    files = {
        "README_CLIENT_START_HERE.md": build_readme(project_name),
        "config/client_demo.json": json.dumps({
            "version": 1,
            "local_only": True,
            "demo_mode_enabled": True,
            "show_simplified_workflow": True,
            "hide_technical_panels_default": True,
            "first_run_completed": False,
            "last_demo_reset": None,
        }, indent=2) + "\n",
    }
    if include_sample_instructions:
        files["content_inbox/ADD_FOOTAGE_HERE.txt"] = "Add MP4, MOV, or M4V footage here, or use Import Footage in the app.\n"

    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for folder in FOLDERS:
            (target / folder).mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(text, encoding="utf-8")

    return {
        "status": "pass",
        "dry_run": dry_run,
        "local_only": True,
        "target": str(target),
        "folders": planned,
        "files": sorted(files),
        "message": "Demo project plan generated." if dry_run else "Demo project created.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a clean HigherKey client demo project folder.")
    parser.add_argument("--target", default="out/demo_project_handoff", help="Target demo project folder.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without creating folders.")
    parser.add_argument("--no-sample-instructions", action="store_true", help="Skip the inbox instruction placeholder.")
    args = parser.parse_args()
    result = create_demo_project(Path(args.target), dry_run=args.dry_run, include_sample_instructions=not args.no_sample_instructions)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
