#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.social_token_vault import clear_token, redact_token_payload, store_token, vault_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local HigherKey social token vault.")
    parser.add_argument("--platform", choices=["instagram", "tiktok"], default="instagram")
    parser.add_argument("--status", action="store_true", help="Print redacted vault status.")
    parser.add_argument("--clear", action="store_true", help="Remove the platform token from local vault storage.")
    parser.add_argument("--store-token-json", default="", help="Path to a local token JSON file. Values are never printed.")
    parser.add_argument("--allow-file-fallback", action="store_true", help="Allow encrypted local placeholder fallback when Keychain is unavailable.")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()
    config = load_config(Path.cwd())
    if args.clear:
        result = {"status": "pass", "action": "clear", **clear_token(config, args.platform)}
    elif args.store_token_json:
        token_path = Path(args.store_token_json).expanduser()
        if not token_path.exists() or not token_path.is_file():
            result = {"status": "fail", "action": "store", "message": "Token JSON file was not found.", "token_values_exposed": False}
        else:
            token_payload = json.loads(token_path.read_text(encoding="utf-8"))
            metadata = store_token(config, args.platform, token_payload, allow_file_fallback=args.allow_file_fallback)
            result = {
                "status": "pass",
                "action": "store",
                "platform": args.platform,
                "metadata": metadata,
                "redacted_token_payload": redact_token_payload(token_payload),
                "token_values_exposed": False,
            }
    else:
        result = {"status": "pass", "action": "status", "vault": vault_status(config), "token_values_exposed": False}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
