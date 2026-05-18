#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from growth_engine.performance_feedback import build_performance_feedback


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local campaign performance feedback summaries.")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    print(json.dumps(build_performance_feedback(Path(args.root)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
