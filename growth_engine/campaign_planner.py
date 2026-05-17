from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .marketing_intelligence import (
    PLATFORM_LABELS,
    PLATFORMS,
    build_marketing_intelligence,
    load_json,
    safe_list,
    write_json,
    write_marketing_markdown,
    write_text,
)


BOARD_COLUMNS = ("Idea", "Ready to Edit", "Ready to Post", "Scheduled", "Posted Manually", "Needs Revision")
MANUAL_STATUSES = {"not_uploaded", "uploaded_manually", "skipped", "needs_revision"}


def _status_key(platform: str, clip_id: str) -> str:
    return f"{platform}:{clip_id}"


def load_manual_status(root: Path) -> dict[str, Any]:
    payload = load_json(root / "analytics" / "manual_post_status.json", {})
    records = payload.get("posts") if isinstance(payload, dict) else {}
    return records if isinstance(records, dict) else {}


def load_exports(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "out" / "social_exports" / "manifest.json", {})
    exports = safe_list(manifest.get("exports"))
    by_clip: dict[str, list[dict[str, Any]]] = {}
    for item in exports:
        if not isinstance(item, dict):
            continue
        clip_id = str(item.get("clip_id") or "")
        if clip_id:
            by_clip.setdefault(clip_id, []).append(item)
    return {"manifest": manifest, "by_clip": by_clip}


def card_status(rec: dict[str, Any], export_info: list[dict[str, Any]], manual_status: dict[str, Any]) -> str:
    platform = str(rec.get("best_platform") or "").lower()
    clip_id = str(rec.get("clip_id") or "")
    record = manual_status.get(_status_key(platform, clip_id), {})
    status = record.get("status") if isinstance(record, dict) else None
    if status == "uploaded_manually":
        return "Posted Manually"
    if status == "needs_revision":
        return "Needs Revision"
    if export_info:
        return "Ready to Post"
    if rec.get("score", 0) >= 82:
        return "Ready to Edit"
    return "Idea"


def build_campaign_cards(root: Path, recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exports = load_exports(root)
    manual_status = load_manual_status(root)
    cards: list[dict[str, Any]] = []
    for index, rec in enumerate(recommendations):
        clip_id = str(rec.get("clip_id") or f"clip_{index + 1}")
        platform = str(rec.get("best_platform") or PLATFORMS[index % len(PLATFORMS)])
        export_info = exports["by_clip"].get(clip_id, [])
        export_folder = ""
        for item in export_info:
            if item.get("platform") == platform or item.get("platform_key") == platform:
                export_folder = str(item.get("output_dir") or item.get("folder") or "")
                break
        if not export_folder and export_info:
            export_folder = str(export_info[0].get("output_dir") or export_info[0].get("folder") or "")
        status = card_status(rec, export_info, manual_status)
        posting_day = (index % 30) + 1
        cards.append({
            "card_id": f"campaign_{clip_id}_{platform}",
            "clip_id": clip_id,
            "title": rec.get("title") or clip_id,
            "audience": rec.get("audience") or "local audience",
            "platform": platform,
            "platform_label": rec.get("platform_label") or PLATFORM_LABELS.get(platform, platform.replace("_", " ").title()),
            "campaign_role": rec.get("campaign_role") or "awareness",
            "content_pillar": infer_pillar(rec, index),
            "hook": rec.get("hook") or rec.get("attack_angle") or "Lead with the strongest moment.",
            "CTA": rec.get("recommended_cta") or rec.get("best_cta") or "Save this and take the next step.",
            "posting_day": posting_day,
            "status": status,
            "export_folder": export_folder or "out/social_exports",
            "score": rec.get("score") or 0,
            "confidence": rec.get("confidence_score") or rec.get("score") or 0,
            "attack_angle": rec.get("attack_angle") or "Make the next action clear.",
            "notes": rec.get("notes") or "Review, upload manually, and track status locally.",
            "upload_checklist": [
                "Open the platform export folder.",
                "Review caption, title, hashtags, and thumbnail.",
                "Upload manually in the selected platform.",
                "Mark this card uploaded after posting.",
            ],
        })
    return cards


def infer_pillar(rec: dict[str, Any], index: int) -> str:
    role = str(rec.get("campaign_role") or "").lower()
    if role in {"proof", "trust", "conversion", "retention", "awareness"}:
        return role
    fallback = ("proof", "process", "transformation", "education", "behind the scenes")
    return fallback[index % len(fallback)]


def build_board(cards: list[dict[str, Any]]) -> dict[str, Any]:
    columns = []
    for name in BOARD_COLUMNS:
        column_cards = [card for card in cards if card.get("status") == name]
        columns.append({
            "name": name,
            "count": len(column_cards),
            "cards": column_cards,
        })
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "columns": columns,
        "cards": cards,
    }


def build_schedule(cards: list[dict[str, Any]], attack: dict[str, Any], days: int = 30) -> dict[str, Any]:
    ordered = sorted(cards, key=lambda card: (-int(card.get("confidence") or 0), int(card.get("posting_day") or 99)))
    seven_day = []
    for day in range(1, 8):
        card = ordered[(day - 1) % len(ordered)] if ordered else {}
        seven_day.append({
            "day": day,
            "platform": card.get("platform_label") or PLATFORM_LABELS[PLATFORMS[(day - 1) % len(PLATFORMS)]],
            "clip_id": card.get("clip_id") or "choose best available clip",
            "hook": card.get("hook") or "Start with the clearest transformation.",
            "CTA": card.get("CTA") or "Save this and take the next step.",
            "audience": card.get("audience") or "local audience",
            "campaign_role": card.get("campaign_role") or "awareness",
            "upload_checklist": card.get("upload_checklist") or [],
            "export_folder": card.get("export_folder") or "out/social_exports",
        })
    pillars = safe_list(attack.get("content_pillars")) or ["proof", "process", "transformation", "education"]
    thirty_day = []
    for week in range(1, 5):
        pillar = pillars[(week - 1) % len(pillars)]
        week_cards = ordered[(week - 1) * 3: week * 3]
        thirty_day.append({
            "week": week,
            "theme": f"{str(pillar).title()} Sprint",
            "content_pillar": pillar,
            "suggested_clips": [card.get("clip_id") for card in week_cards if card.get("clip_id")],
            "goal": "Build recognition, trust, and action through repeated short-form angles.",
            "notes": "Upload manually and mark post status locally after publishing.",
        })
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "days_requested": days,
        "seven_day_schedule": seven_day,
        "thirty_day_schedule": thirty_day,
    }


def build_campaign_brief(root: Path, board: dict[str, Any], schedule: dict[str, Any], marketing: dict[str, Any]) -> dict[str, Any]:
    attack = marketing.get("market_attack_plan", {})
    cards = safe_list(board.get("cards"))
    role_counts = Counter(card.get("campaign_role") for card in cards)
    platform_counts = Counter(card.get("platform") for card in cards)
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "campaign_thesis": attack.get("campaign_thesis", "Lead with proof and make the next action simple."),
        "audience": attack.get("primary_market", "local short-form audience"),
        "positioning": attack.get("positioning_statement", "HigherKey prepares social-ready clips for manual upload."),
        "attack_angle": (cards[0].get("attack_angle") if cards else "Start with the strongest hook."),
        "content_pillars": safe_list(attack.get("content_pillars")),
        "hook_bank": safe_list(attack.get("hook_bank")),
        "CTA_bank": safe_list(attack.get("cta_bank")),
        "role_mix": dict(role_counts),
        "platform_mix": dict(platform_counts),
        "next_post": cards[0] if cards else None,
        "seven_day_count": len(safe_list(schedule.get("seven_day_schedule"))),
        "thirty_day_count": len(safe_list(schedule.get("thirty_day_schedule"))),
    }


def build_client_plan(board: dict[str, Any], schedule: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    cards = safe_list(board.get("cards"))
    next_card = cards[0] if cards else {}
    return {
        "version": 1,
        "updated_at": utc_now(),
        "status": "ready" if cards else "needs_input",
        "local_only": True,
        "manual_upload_only": True,
        "message": "Campaign plan ready for manual upload." if cards else "Build Marketing Plan after approving clips.",
        "next_action": "Upload the next recommended post manually." if cards else "Approve clips, then build the campaign plan.",
        "next_post": next_card,
        "seven_day_schedule": safe_list(schedule.get("seven_day_schedule")),
        "campaign_thesis": brief.get("campaign_thesis"),
    }


def markdown_bullets(items: list[Any]) -> str:
    if not items:
        return "- None yet"
    return "\n".join(f"- {item}" for item in items)


def write_campaign_markdown(root: Path, board: dict[str, Any], schedule: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    seven = safe_list(schedule.get("seven_day_schedule"))
    thirty = safe_list(schedule.get("thirty_day_schedule"))
    write_text(out / "posting_schedule.md", "\n".join([
        "# 7-Day Posting Schedule",
        "",
        "Manual upload only. HigherKey prepares the files; the operator uploads them.",
        "",
        *[
            f"## Day {item.get('day')}\n- Platform: {item.get('platform')}\n- Clip: {item.get('clip_id')}\n- Hook: {item.get('hook')}\n- CTA: {item.get('CTA')}\n- Export folder: {item.get('export_folder')}"
            for item in seven
        ],
    ]))
    write_text(out / "30_day_campaign_plan.md", "\n".join([
        "# 30-Day Campaign Plan",
        "",
        *[
            f"## Week {item.get('week')}: {item.get('theme')}\n- Pillar: {item.get('content_pillar')}\n- Goal: {item.get('goal')}\n- Clips: {', '.join(item.get('suggested_clips') or ['choose best available clips'])}\n- Notes: {item.get('notes')}"
            for item in thirty
        ],
    ]))
    write_text(out / "campaign_brief.md", "\n".join([
        "# Campaign Brief",
        "",
        f"Campaign thesis: {brief.get('campaign_thesis')}",
        f"Audience: {brief.get('audience')}",
        f"Positioning: {brief.get('positioning')}",
        f"Attack angle: {brief.get('attack_angle')}",
        "",
        "## Content Pillars",
        markdown_bullets(safe_list(brief.get("content_pillars"))),
        "",
        "## Hook Bank",
        markdown_bullets(safe_list(brief.get("hook_bank"))),
        "",
        "## CTA Bank",
        markdown_bullets(safe_list(brief.get("CTA_bank"))),
        "",
        "Manual upload reminder: HigherKey prepares platform folders; no direct posting APIs are configured.",
    ]))
    return {
        "posting_schedule": relative_path(out / "posting_schedule.md", root),
        "thirty_day_campaign_plan": relative_path(out / "30_day_campaign_plan.md", root),
        "campaign_brief": relative_path(out / "campaign_brief.md", root),
    }


def build_campaign_plan(root: Path, days: int = 30, dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    marketing = build_marketing_intelligence(project_root)
    write_marketing_markdown(project_root, marketing)
    recommendations = safe_list(marketing.get("marketing_recommendations"))
    cards = build_campaign_cards(project_root, recommendations)
    board = build_board(cards)
    schedule = build_schedule(cards, marketing.get("market_attack_plan", {}), days=days)
    brief = build_campaign_brief(project_root, board, schedule, marketing)
    client = build_client_plan(board, schedule, brief)
    analytics = project_root / "analytics"
    outputs = {
        "campaign_board": analytics / "campaign_board.json",
        "posting_schedule": analytics / "posting_schedule.json",
        "content_calendar_board": analytics / "content_calendar_board.json",
        "campaign_brief": analytics / "campaign_brief.json",
        "client_campaign_plan": analytics / "client_campaign_plan.json",
    }
    content_calendar_board = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "cards_by_pillar": group_cards(cards, "content_pillar"),
        "cards_by_platform": group_cards(cards, "platform"),
    }
    markdown_outputs = {} if dry_run else write_campaign_markdown(project_root, board, schedule, brief)
    if not dry_run:
        write_json(outputs["campaign_board"], board)
        write_json(outputs["posting_schedule"], schedule)
        write_json(outputs["content_calendar_board"], content_calendar_board)
        write_json(outputs["campaign_brief"], brief)
        write_json(outputs["client_campaign_plan"], client)
    return {
        "ok": True,
        "dry_run": dry_run,
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "cards": len(cards),
        "ready_to_post": len([card for card in cards if card.get("status") == "Ready to Post"]),
        "scheduled_posts": len(safe_list(schedule.get("seven_day_schedule"))),
        "analytics_outputs": {key: relative_path(path, project_root) for key, path in outputs.items()},
        "markdown_outputs": markdown_outputs,
        "board": board if dry_run else None,
    }


def group_cards(cards: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for card in cards:
        value = str(card.get(key) or "uncategorized")
        grouped.setdefault(value, []).append(str(card.get("clip_id") or card.get("title")))
    return grouped


def update_manual_post_status(root: Path, clip_id: str, platform: str, status: str, notes: str = "") -> dict[str, Any]:
    normalized = status.strip().lower()
    if normalized not in MANUAL_STATUSES:
        raise ValueError(f"Unsupported manual post status: {status}")
    analytics = root / "analytics"
    payload = load_json(analytics / "manual_post_status.json", {})
    posts = payload.get("posts") if isinstance(payload, dict) else {}
    if not isinstance(posts, dict):
        posts = {}
    key = _status_key(platform.strip().lower(), clip_id)
    posts[key] = {
        "clip_id": clip_id,
        "platform": platform.strip().lower(),
        "status": normalized,
        "notes": notes,
        "updated_at": utc_now(),
        "local_only": True,
    }
    result = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_tracking_only": True,
        "direct_posting_apis": False,
        "posts": posts,
    }
    write_json(analytics / "manual_post_status.json", result)
    return result
