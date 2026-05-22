#!/usr/bin/env python3
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.config import load_config
from growth_engine.index import utc_now
from growth_engine.json_store import save_json_file
from growth_engine.oauth_state import create_oauth_state, oauth_state_status, validate_oauth_state


SENSITIVE_KEYS = {"code", "state", "access_token", "refresh_token", "id_token", "client_secret"}


def redacted_params(params: dict[str, list[str]]) -> dict[str, str]:
    redacted = {}
    for key, values in params.items():
        value = values[0] if values else ""
        redacted[key] = "redacted" if key.lower() in SENSITIVE_KEYS else value[:120]
    return redacted


def write_status(root: Path, payload: dict) -> None:
    config = load_config(root)
    save_json_file(config.analytics_dir / "social_oauth_status.json", payload)
    client_payload = dict(payload)
    client_payload["client_safe"] = True
    client_payload["token_values_exposed"] = False
    save_json_file(config.analytics_dir / "client_social_oauth_status.json", client_payload)


def dry_run_status(root: Path, platform: str, params: dict[str, list[str]] | None = None, *, auto_state: bool = False) -> dict:
    config = load_config(root)
    query = params or {}
    if auto_state and not query.get("state"):
        query = dict(query)
        query["state"] = [create_oauth_state(config, platform)["state"]]
    received_state = query.get("state", [""])[0] if query.get("state") else ""
    state_validation = validate_oauth_state(config, platform, received_state)
    state_valid = state_validation.get("valid") is True
    has_code = bool(query.get("code"))
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "platform": platform,
        "host": "127.0.0.1",
        "port": 8787,
        "dry_run": True,
        "live_exchange_enabled": False,
        "authorization_code_received": has_code,
        "token_exchange_ready": bool(has_code and state_valid),
        "token_exchange_performed": False,
        "token_values_exposed": False,
        "tokens_stored": False,
        "params": redacted_params(query),
        "state_validation": state_validation,
        "oauth_state_status": oauth_state_status(config),
        "message": "OAuth callback dry run complete. Authorization code values are redacted. Live token exchange is not enabled by default." if state_valid else state_validation.get("message"),
    }
    write_status(root, payload)
    return payload


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "HigherKeyOAuthDryRun/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        platform = "instagram" if "/meta/" in parsed.path or "instagram" in parsed.path else ("tiktok" if "tiktok" in parsed.path else "callback")
        payload = dry_run_status(Path(self.server.root), platform, params, auto_state=False)  # type: ignore[attr-defined]
        ok = payload.get("state_validation", {}).get("valid") is True
        body = (b"HigherKey OAuth dry run received. You can close this window." if ok else b"HigherKey OAuth callback rejected because state validation failed.")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.last_payload = payload  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local HigherKey OAuth callback placeholder.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--platform", default="dry_run")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--serve", action="store_true", help="Bind 127.0.0.1 and handle one callback request.")
    parser.add_argument("--callback-query", default="", help="Optional callback query string for dry-run parsing.")
    parser.add_argument("--live-exchange", action="store_true", help="Reserved for future official token exchange; disabled unless explicitly implemented.")
    args = parser.parse_args()
    root = Path.cwd()
    if not args.serve:
        params = parse_qs(args.callback_query.lstrip("?"))
        payload = dry_run_status(root, args.platform, params, auto_state=not params)
        print(json.dumps({"status": "pass", **payload}, indent=2, sort_keys=True))
        return 0 if payload.get("state_validation", {}).get("valid") is True else 1
    server = HTTPServer(("127.0.0.1", args.port), CallbackHandler)
    server.root = str(root)  # type: ignore[attr-defined]
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "host": "127.0.0.1",
        "port": args.port,
        "dry_run": True,
        "live_exchange_enabled": False,
        "token_exchange_performed": False,
        "token_values_exposed": False,
        "tokens_stored": False,
        "message": "OAuth callback placeholder is listening for one local dry-run request.",
    }
    write_status(root, payload)
    server.handle_request()
    print(json.dumps({"status": "pass", "served": True, "token_values_exposed": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
