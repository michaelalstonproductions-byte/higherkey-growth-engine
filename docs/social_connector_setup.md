# HigherKey Social Connector Setup

HigherKey Social Connector Studio is local-first. It prepares drafts, schedules posts, checks account readiness, and runs dry-run publisher tests. Manual upload remains available for every platform.

## Safety Rules

- HigherKey uses official Instagram and TikTok APIs only.
- No password login is supported.
- No scraping or browser automation is supported.
- No tokens, app secrets, refresh tokens, or user-specific connector config should be committed.
- `config/social_connectors.json` is local-only and ignored by git.
- Live posting stays disabled unless credentials, account authorization, live mode, due scheduling, single-draft selection, approval receipt, exact confirmation phrase, and explicit user approval are all present.
- Bulk live publishing and background autoposting are blocked.

## Instagram Overview

Instagram Reels publishing must use the official Meta/Instagram content publishing flow. Setup requires a Meta app, an Instagram professional account, and permissions such as:

- `instagram_business_basic`
- `instagram_business_content_publish`

Environment variable placeholders:

```bash
export HIGHERKEY_META_APP_ID="..."
export HIGHERKEY_META_APP_SECRET="..."
```

Configured redirect URI:

```text
http://127.0.0.1:8787/oauth/meta/callback
```

Instagram publishing may require hosted media or supported upload handling. If HigherKey cannot provide media through an official supported flow, use manual upload.

## TikTok Overview

TikTok publishing must use the official TikTok Content Posting API. Setup requires an approved TikTok app, user authorization, and scope:

- `video.publish`

Environment variable placeholders:

```bash
export HIGHERKEY_TIKTOK_CLIENT_KEY="..."
export HIGHERKEY_TIKTOK_CLIENT_SECRET="..."
```

Configured redirect URI:

```text
http://127.0.0.1:8787/oauth/tiktok/callback
```

Unaudited TikTok clients may be private-post restricted. Use dry run first and confirm app review status before enabling live mode.

## Dry-Run Workflow

1. Build drafts in the Scheduler or with `python3 scripts/build_post_composer_drafts.py`.
2. Paste or edit final post text in Post Composer.
3. Run `python3 scripts/check_social_connectors.py`.
4. Run `python3 scripts/check_publish_readiness.py`.
5. Run `python3 scripts/run_social_publisher.py --dry-run --due-now --json`.
6. Upload manually when credentials, permissions, or live approval are missing.

## Controlled Live Publish Workflow

V6.5 supports only controlled single-post live publish readiness. Use this sequence:

1. Build and edit a Post Composer draft.
2. Schedule the draft for a due time and set `publish_mode` to `live_api`.
3. Run `python3 scripts/check_live_publish_readiness.py --dry-run --platform all`.
4. Run `python3 scripts/run_social_publisher.py --live-sandbox --dry-run --due-now --json`.
5. Create an approval receipt only after entering: `I understand this will attempt a real platform publish.`
6. Attempt one supported draft only. Unsupported platforms stay manual upload.

Instagram Reels and TikTok are the only supported live-readiness platforms. YouTube Shorts and Facebook Reels are manual upload fallback only. QA must never run live platform calls.

## OAuth Callback Placeholder

V6.4 keeps the callback local and adds OAuth readiness plus token vault status:

```bash
python3 scripts/run_social_oauth_callback.py --dry-run
python3 scripts/check_social_oauth_readiness.py
python3 scripts/check_social_token_vault.py
```

It binds to `127.0.0.1` only when explicitly started with `--serve`. Dry run records redacted callback state in `analytics/social_oauth_status.json` and does not exchange or store real tokens.

## Token Vault

HigherKey prefers macOS Keychain for local token storage. Analytics and client status files contain only metadata such as provider availability, redacted token presence, expiration, and granted scopes. Token values must never be written to `analytics/`, logs, dashboard HTML, source files, or committed config.

Local encrypted-file fallback is disabled by default and should only be used with a local vault key and an explicit operator choice. Live posting remains blocked unless the official connector is enabled, credentials exist, OAuth has completed, required permissions/scopes are present, live mode is enabled, the scheduled post is due, and the user explicitly approves.
