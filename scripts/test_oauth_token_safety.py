#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.oauth_state import create_oauth_state, validate_oauth_state
from growth_engine.social_token_vault import redact_token_payload
from scripts.run_social_oauth_callback import dry_run_status


FORBIDDEN = (
    "tok_live_nested_secret",
    "refresh_nested_secret",
    "code_nested_secret",
    "client_nested_secret",
    "Bearer secretbearertoken",
)


def assert_no_forbidden(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for term in FORBIDDEN:
        assert term not in text, f"{term} leaked into {path}"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="higherkey_oauth_safety_", dir="/private/tmp") as tmp:
        root = Path(tmp)
        for name in ("analytics", "config"):
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "config" / "social_connectors.example.json", root / "config" / "social_connectors.example.json")
        config = load_config(root)

        state = create_oauth_state(config, "instagram")
        valid = validate_oauth_state(config, "instagram", state["state"])
        assert valid["status"] == "valid_state" and valid["valid"] is True, valid
        missing = validate_oauth_state(config, "instagram", "")
        assert missing["status"] == "missing_state" and missing["valid"] is False, missing
        invalid = validate_oauth_state(config, "instagram", "not-the-state")
        assert invalid["status"] == "invalid_state" and invalid["valid"] is False, invalid
        expired_state = create_oauth_state(config, "tiktok", ttl_minutes=-1)
        expired = validate_oauth_state(config, "tiktok", expired_state["state"])
        assert expired["status"] == "expired_state" and expired["valid"] is False, expired

        callback_state = create_oauth_state(config, "instagram")
        callback = dry_run_status(root, "instagram", {"state": [callback_state["state"]], "code": ["code_nested_secret"]})
        assert callback["state_validation"]["status"] == "valid_state", callback
        rejected = dry_run_status(root, "instagram", {"code": ["code_nested_secret"]})
        assert rejected["state_validation"]["status"] == "missing_state", rejected

        nested = {
            "access_token": "tok_live_nested_secret",
            "nested": {
                "refresh_token": "refresh_nested_secret",
                "items": [
                    {"authorization_code": "code_nested_secret"},
                    {"headers": {"Authorization": "Bearer secretbearertoken"}},
                ],
            },
            "client": {"client_secret": "client_nested_secret"},
            "safe_scope": ["video.publish"],
        }
        redacted = redact_token_payload(nested)
        redacted_text = json.dumps(redacted)
        for term in FORBIDDEN:
            assert term not in redacted_text, redacted
        assert "[REDACTED]" in redacted_text, redacted

        for path in [
            config.analytics_dir / "oauth_state_status.json",
            config.analytics_dir / "client_oauth_state_status.json",
            config.analytics_dir / "social_oauth_status.json",
            config.analytics_dir / "client_social_oauth_status.json",
        ]:
            assert_no_forbidden(path)

    print(json.dumps({
        "status": "pass",
        "valid_state": True,
        "missing_state_rejected": True,
        "invalid_state_rejected": True,
        "expired_state_rejected": True,
        "nested_token_redacted": True,
        "token_values_exposed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
