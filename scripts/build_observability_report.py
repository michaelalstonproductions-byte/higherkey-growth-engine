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
from growth_engine.observability import build_observability_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HigherKey local observability reports.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    args = parser.parse_args()
    config = load_config(Path(args.root).resolve())
    result = build_observability_report(config)
    print(json.dumps({
        "status": "pass",
        "runtime_metrics": "analytics/runtime_metrics.json",
        "client_metrics": "analytics/client_metrics.json",
        "observability_report": "analytics/observability_report.json",
        "client_observability": "analytics/client_observability.json",
        "health_score": result["client_observability"]["health_score"],
        "health_label": result["client_observability"]["health_label"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
