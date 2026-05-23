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
from growth_engine.editing_delivery import verify_edited_delivery_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify edited asset delivery package safety.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(Path.cwd())
    result = verify_edited_delivery_package(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
