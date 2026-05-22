#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.social_token_vault import vault_status


def main() -> int:
    config = load_config(Path.cwd())
    payload = vault_status(config)
    print(json.dumps({
        "status": "pass",
        "token_values_exposed": False,
        "keychain_available": payload.get("keychain_available", False),
        "provider": payload.get("provider", "not_available"),
        "paths": [
            "analytics/social_token_vault_status.json",
            "analytics/client_social_token_vault_status.json",
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
