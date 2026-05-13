#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.local_ai import build_metadata_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild local searchable metadata index")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--enable-whisper", action="store_true", help="Run optional local Whisper CLI if installed.")
    parser.add_argument("--enable-ocr", action="store_true", help="Run optional local OCR adapter if installed.")
    args = parser.parse_args()

    summary = build_metadata_index(Path(args.root), enable_whisper=args.enable_whisper, enable_ocr=args.enable_ocr)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
