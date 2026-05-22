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


SENSITIVE_KEYS = {"code", "access_token", "refresh_token", "id_token", "client_secret"}


def redacted_params(params: dict[str, list[str]]) -> dict[str, str]:
    redacted = {}
    for key, values in params.items():
        value = values[0] if values else ""
        redacted[key] = "redacted" if key.lower() in SENSITIVE_KEYS else value[:120]
    return redacted


def write_status(root: Path, payload: dict) -> None:
    config = load_config(root)
    save_json_file(config.analytics_dir / "social_oauth_status.json", payload)


def dry_run_status(root: Path, platform: str, params: dict[str, list[str]] | None = None) -> dict:
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "platform": platform,
        "host": "127.0.0.1",
        "port": 8787,
        "dry_run": True,
        "live_exchange_enabled": False,
        "token_values_exposed": False,
        "tokens_stored": False,
        "params": redacted_params(params or {}),
        "message": "OAuth callback dry run complete. Live token exchange is not enabled by default.",
    }
    write_status(root, payload)
    return payload


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "HigherKeyOAuthDryRun/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        payload = dry_run_status(Path(self.server.root), "callback", params)  # type: ignore[attr-defined]
        body = b"HigherKey OAuth dry run received. You can close this window."
        self.send_response(200)
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
    args = parser.parse_args()
    root = Path.cwd()
    if not args.serve:
        params = parse_qs(args.callback_query.lstrip("?"))
        payload = dry_run_status(root, args.platform, params)
        print(json.dumps({"status": "pass", **payload}, indent=2, sort_keys=True))
        return 0
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
