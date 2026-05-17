from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now


PLATFORMS = ("tiktok", "instagram_reels", "youtube_shorts", "facebook_reels")
PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "instagram_reels": "Instagram Reels",
    "youtube_shorts": "YouTube Shorts",
    "facebook_reels": "Facebook Reels",
}


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text_bits(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if not isinstance(item, (dict, list)))
    return " ".join(parts).lower()


def score_clip(entry: dict[str, Any]) -> int:
    try:
        return int(float(entry.get("score") or entry.get("package", {}).get("score") or 0))
    except (TypeError, ValueError):
        return 0


def clip_title(entry: dict[str, Any], package: dict[str, Any]) -> str:
    return (
        package.get("suggested_title")
        or package.get("hook")
        or entry.get("optimized_title")
        or entry.get("clip_id")
        or "Untitled clip"
    )


def approved_ids(root: Path) -> set[str]:
    payload = load_json(root / "queue" / "approved_reviews.json", {})
    selected: set[str] = set()
    for key in ("approved_clip_ids", "approved_entry_ids"):
        for value in safe_list(payload.get(key)):
            selected.add(str(value))
    for item in safe_list(payload.get("approved")):
        if isinstance(item, str):
            selected.add(item)
        elif isinstance(item, dict):
            for key in ("id", "entry_id", "queue_id", "clip_id"):
                if item.get(key):
                    selected.add(str(item[key]))
    return selected


def selected_entries(root: Path) -> list[dict[str, Any]]:
    queue = load_json(root / "queue" / "review_queue.json", {"entries": []})
    selected = approved_ids(root)
    entries = safe_list(queue.get("entries"))
    chosen: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") in selected or entry.get("clip_id") in selected or score_clip(entry) >= 82:
            chosen.append(entry)
    return sorted(chosen, key=score_clip, reverse=True)[:24]


def load_package(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    package_path = entry.get("package_path")
    if not package_path:
        return {}
    return load_json(root / str(package_path), {})


def load_profile(root: Path) -> tuple[dict[str, Any], str]:
    private_profile = root / "config" / "marketing_profile.json"
    example_profile = root / "config" / "marketing_profile.example.json"
    if private_profile.exists():
        return load_json(private_profile, {}), relative_path(private_profile, root)
    return load_json(example_profile, {}), relative_path(example_profile, root)


@dataclass(frozen=True)
class SegmentMatch:
    name: str
    confidence: int
    motivation: str
    objection: str
    cta_style: str
    why: str


def infer_segment(profile: dict[str, Any], entry: dict[str, Any], package: dict[str, Any]) -> SegmentMatch:
    text = text_bits(
        entry.get("scene_labels"),
        entry.get("metadata", {}),
        package.get("caption"),
        package.get("hashtags"),
        package.get("platform_notes"),
        package.get("suggested_title"),
    )
    best: tuple[int, dict[str, Any]] | None = None
    for segment in safe_list(profile.get("audience_segments")):
        if not isinstance(segment, dict):
            continue
        keywords = text_bits(segment.get("name"), segment.get("description"), segment.get("motivations"))
        score = 0
        for token in keywords.split():
            if len(token) > 3 and token in text:
                score += 5
        if "action" in text or "motion" in text:
            score += 8
        if "proof" in text or "trust" in text:
            score += 8
        if "fitness" in text or "performance" in text:
            score += 10
        if best is None or score > best[0]:
            best = (score, segment)
    fallback_segments = safe_list(profile.get("audience_segments"))
    segment = best[1] if best else (fallback_segments[0] if fallback_segments and isinstance(fallback_segments[0], dict) else {})
    motivations = safe_list(segment.get("motivations")) or safe_list(profile.get("psychographics", {}).get("motivations")) or ["growth"]
    objections = safe_list(segment.get("objections")) or safe_list(profile.get("psychographics", {}).get("objections")) or ["not sure where to start"]
    confidence = min(96, max(58, score_clip(entry) - 8 + (best[0] if best else 0)))
    return SegmentMatch(
        name=str(segment.get("name") or "high-intent creators"),
        confidence=confidence,
        motivation=str(motivations[0]),
        objection=str(objections[0]),
        cta_style=str(segment.get("cta_style") or profile.get("call_to_action_style") or "save this and take the next step"),
        why="Matched caption, scene labels, hook timing, and local package signals.",
    )


def best_platform(entry: dict[str, Any], package: dict[str, Any]) -> tuple[str, str]:
    score = score_clip(entry)
    duration = float(package.get("duration") or entry.get("duration") or 0)
    labels = set(str(label).lower() for label in safe_list(entry.get("scene_labels") or package.get("scene_labels")))
    if score >= 84 and ("action" in labels or duration <= 35):
        return "tiktok", "Strong early hook and short-form discovery fit."
    if "trust" in labels or "proof" in labels:
        return "instagram_reels", "Best fit for trust-building and repeat exposure."
    if duration <= 60:
        return "youtube_shorts", "Shorts-compatible duration and searchable topic fit."
    return "facebook_reels", "Useful for local/community reach and broad manual upload."


def campaign_role(entry: dict[str, Any], package: dict[str, Any]) -> str:
    text = text_bits(package.get("caption"), package.get("platform_notes"), entry.get("scene_labels"))
    if "proof" in text or "result" in text:
        return "proof"
    if "how" in text or "step" in text or "process" in text:
        return "trust"
    if score_clip(entry) >= 86:
        return "awareness"
    return "conversion"


def attack_angle(segment: SegmentMatch, entry: dict[str, Any], package: dict[str, Any]) -> str:
    hook = package.get("hook") or package.get("suggested_title") or "Make the next move simple"
    if segment.motivation in {"growth", "momentum", "confidence"}:
        return f"Make the first move feel simple: {hook}"
    if segment.motivation in {"trust", "authority"}:
        return f"Show proof before asking for action: {hook}"
    return f"Lead with the clearest transformation: {hook}"


def cta_for(segment: SegmentMatch, platform: str) -> str:
    if platform == "tiktok":
        return "Save this and start today."
    if platform == "instagram_reels":
        return "Share this with someone who needs the next step."
    if platform == "youtube_shorts":
        return "Watch the next clip and build the sequence."
    if platform == "facebook_reels":
        return "Message us when you are ready to use your footage."
    return segment.cta_style


def recommendation_for(root: Path, entry: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    package = load_package(root, entry)
    segment = infer_segment(profile, entry, package)
    platform, platform_reason = best_platform(entry, package)
    role = campaign_role(entry, package)
    title = clip_title(entry, package)
    return {
        "clip_id": entry.get("clip_id"),
        "queue_entry_id": entry.get("id"),
        "title": title,
        "hook": package.get("hook") or title,
        "score": score_clip(entry),
        "audience": segment.name,
        "demographic_fit": {
            "age_ranges": safe_list(profile.get("demographics", {}).get("age_ranges")) or ["18-34"],
            "locations": safe_list(profile.get("demographics", {}).get("locations")) or ["local market"],
            "confidence": segment.confidence,
        },
        "psychographic_fit": {
            "motivation": segment.motivation,
            "objection": segment.objection,
            "identity_signal": (safe_list(profile.get("psychographics", {}).get("identity_signals")) or ["creator"])[0],
        },
        "likely_motivation": segment.motivation,
        "likely_objection": segment.objection,
        "best_cta": cta_for(segment, platform),
        "best_platform": platform,
        "platform_label": PLATFORM_LABELS[platform],
        "platform_reason": platform_reason,
        "confidence_score": segment.confidence,
        "why_this_audience": segment.why,
        "campaign_role": role,
        "recommended_caption_style": "short hook, one useful insight, clear manual-upload CTA",
        "recommended_cta": cta_for(segment, platform),
        "hashtag_strategy": "Use 3-6 specific tags tied to audience, category, and series.",
        "suggested_posting_window": "Test morning or early evening local time.",
        "attack_angle": attack_angle(segment, entry, package),
        "notes": "Local deterministic recommendation. Review before posting manually.",
        "clip_path": entry.get("clip_path"),
        "package_path": entry.get("package_path"),
        "export_status": export_status(root, entry.get("clip_id")),
    }


def export_status(root: Path, clip_id: str | None) -> dict[str, Any]:
    manifest = load_json(root / "out" / "social_exports" / "manifest.json", {})
    exports = [item for item in safe_list(manifest.get("exports")) if item.get("clip_id") == clip_id]
    return {
        "ready": bool(exports),
        "count": len(exports),
        "platforms": [item.get("platform") for item in exports],
        "folder": manifest.get("output_dir", "out/social_exports"),
    }


def build_audience_profile(profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    segment_counts = Counter(item["audience"] for item in recommendations)
    top_segments = []
    for segment in safe_list(profile.get("audience_segments")):
        if not isinstance(segment, dict):
            continue
        name = str(segment.get("name") or "Audience")
        top_segments.append({
            "name": name,
            "description": segment.get("description", ""),
            "clip_count": segment_counts.get(name, 0),
            "demographic_fit": segment.get("age_ranges") or profile.get("demographics", {}).get("age_ranges", []),
            "motivation": (safe_list(segment.get("motivations")) or ["growth"])[0],
            "objection": (safe_list(segment.get("objections")) or ["not sure where to start"])[0],
            "cta_style": segment.get("cta_style") or profile.get("call_to_action_style", ""),
        })
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "brand_name": profile.get("brand_name"),
        "target_audience": profile.get("target_audience"),
        "demographics": profile.get("demographics", {}),
        "psychographics": profile.get("psychographics", {}),
        "segments": top_segments,
    }


def build_market_attack_plan(profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    top = recommendations[:7]
    pillars = safe_list(profile.get("content_pillars")) or ["proof", "process", "transformation"]
    hook_bank = [item["hook"] for item in top if item.get("hook")][:10]
    cta_bank = list(dict.fromkeys(item["recommended_cta"] for item in recommendations if item.get("recommended_cta")))[:10]
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "primary_market": profile.get("target_audience", "high-intent short-form viewers"),
        "secondary_market": "People already consuming adjacent creator, business, or transformation content.",
        "positioning_statement": f"{profile.get('brand_name', 'HigherKey')} turns local footage into clips, captions, and social packs that are ready for manual upload.",
        "content_pillars": pillars,
        "campaign_thesis": "Lead with proof, make the next action simple, and sequence the best clips into a short campaign.",
        "hook_bank": hook_bank,
        "cta_bank": cta_bank,
        "content_sequence": ["awareness", "trust", "proof", "conversion", "retention"],
        "posting_strategy": "Post the highest-confidence clip first, rotate platforms, then repeat the strongest pillar with a new angle.",
        "risk_notes": ["Avoid unsupported performance claims.", "Review captions before manual upload.", "Do not imply automatic posting."],
        "what_to_avoid": ["generic hashtags", "long setup before the hook", "unclear next step", "direct posting language"],
        "next_7_posts": next_posts(recommendations, 7),
        "next_30_day_content_themes": thirty_day_themes(pillars),
    }


def next_posts(recommendations: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    posts = []
    source = recommendations or []
    for index in range(count):
        item = source[index % len(source)] if source else {}
        posts.append({
            "day": index + 1,
            "platform": item.get("platform_label", PLATFORM_LABELS[PLATFORMS[index % len(PLATFORMS)]]),
            "clip_id": item.get("clip_id", "choose best available clip"),
            "hook": item.get("hook", "Start with the clearest transformation."),
            "cta": item.get("recommended_cta", "Save this and take the next step."),
        })
    return posts


def thirty_day_themes(pillars: list[str]) -> list[dict[str, Any]]:
    themes = []
    for day in range(1, 31):
        pillar = pillars[(day - 1) % len(pillars)]
        themes.append({
            "day": day,
            "content_pillar": pillar,
            "topic": f"{pillar.title()} angle {((day - 1) // len(pillars)) + 1}",
            "goal": "Build trust, clarity, and repeated audience recognition.",
        })
    return themes


def build_content_strategy(profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    role_counts = Counter(item["campaign_role"] for item in recommendations)
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "content_pillars": safe_list(profile.get("content_pillars")),
        "role_mix": dict(role_counts),
        "recommended_sequence": ["best hook", "proof clip", "process clip", "audience objection", "clear CTA"],
        "caption_style": "Plainspoken, short, useful, and action-oriented.",
        "hashtag_strategy": "Specific tags beat generic reach tags. Use audience, category, and series tags.",
    }


def build_platform_strategy(profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    platform_counts = Counter(item["best_platform"] for item in recommendations)
    platforms = {}
    for key in PLATFORMS:
        platforms[key] = {
            "label": PLATFORM_LABELS[key],
            "recommended_clips": platform_counts.get(key, 0),
            "role": profile.get("platforms", {}).get(PLATFORM_LABELS[key], {}).get("role", "manual upload channel"),
            "guidance": platform_guidance(key),
        }
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "platforms": platforms,
    }


def platform_guidance(platform: str) -> str:
    return {
        "tiktok": "Lead with the hook in the first second and keep the caption direct.",
        "instagram_reels": "Use trust-building captions, clean thumbnail, and a share/save CTA.",
        "youtube_shorts": "Keep title searchable and under 70 characters when possible.",
        "facebook_reels": "Use simple language and community-friendly context.",
    }[platform]


def build_campaign_calendar(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "next_7_posts": next_posts(recommendations, 7),
        "next_30_day_content_themes": thirty_day_themes(["proof", "process", "transformation", "education", "behind the scenes"]),
    }


def build_marketing_intelligence(root: Path) -> dict[str, Any]:
    project_root = root.resolve()
    profile, profile_source = load_profile(project_root)
    entries = selected_entries(project_root)
    recommendations = [recommendation_for(project_root, entry, profile) for entry in entries]
    recommendations = sorted(recommendations, key=lambda item: item.get("confidence_score", 0), reverse=True)
    audience = build_audience_profile(profile, recommendations)
    attack = build_market_attack_plan(profile, recommendations)
    content = build_content_strategy(profile, recommendations)
    platform = build_platform_strategy(profile, recommendations)
    calendar = build_campaign_calendar(recommendations)
    brief = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "profile_source": profile_source,
        "brand_name": profile.get("brand_name", "HigherKey"),
        "summary": "Turn approved clips into a focused manual-upload market attack plan.",
        "approved_or_high_scoring_clips": len(recommendations),
        "primary_market": attack["primary_market"],
        "positioning_statement": attack["positioning_statement"],
        "next_best_post": recommendations[0] if recommendations else None,
        "manual_upload_only": True,
        "direct_posting_apis": False,
    }

    analytics = project_root / "analytics"
    write_json(analytics / "marketing_brief.json", brief)
    write_json(analytics / "audience_profile.json", audience)
    write_json(analytics / "market_attack_plan.json", attack)
    write_json(analytics / "content_strategy.json", content)
    write_json(analytics / "platform_strategy.json", platform)
    write_json(analytics / "campaign_calendar.json", calendar)
    write_json(analytics / "marketing_recommendations.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "recommendations": recommendations,
    })
    return {
        "brief": brief,
        "audience_profile": audience,
        "market_attack_plan": attack,
        "content_strategy": content,
        "platform_strategy": platform,
        "campaign_calendar": calendar,
        "marketing_recommendations": recommendations,
    }


def markdown_list(items: list[Any]) -> str:
    if not items:
        return "- None yet\n"
    return "\n".join(f"- {item}" for item in items) + "\n"


def write_marketing_markdown(root: Path, result: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    brief = result["brief"]
    attack = result["market_attack_plan"]
    platform = result["platform_strategy"]
    calendar = result["campaign_calendar"]
    recommendations = result["marketing_recommendations"]

    write_text(out / "marketing_brief.md", "\n".join([
        "# Marketing Brief",
        "",
        f"Brand: {brief['brand_name']}",
        f"Primary market: {brief['primary_market']}",
        f"Positioning: {brief['positioning_statement']}",
        "",
        "Manual upload only. No direct posting APIs are configured.",
    ]))
    write_text(out / "market_attack_plan.md", "\n".join([
        "# Market Attack Plan",
        "",
        f"Campaign thesis: {attack['campaign_thesis']}",
        "",
        "## Content Pillars",
        markdown_list(attack["content_pillars"]),
        "## Hook Bank",
        markdown_list(attack["hook_bank"]),
        "## CTA Bank",
        markdown_list(attack["cta_bank"]),
        "## What To Avoid",
        markdown_list(attack["what_to_avoid"]),
    ]))
    write_text(out / "content_calendar.md", "\n".join([
        "# Content Calendar",
        "",
        "## Next 7 Posts",
        "\n".join(f"- Day {item['day']}: {item['platform']} · {item['clip_id']} · {item['cta']}" for item in calendar["next_7_posts"]),
        "",
        "## 30-Day Themes",
        "\n".join(f"- Day {item['day']}: {item['content_pillar']} · {item['topic']}" for item in calendar["next_30_day_content_themes"]),
    ]))
    write_text(out / "platform_strategy.md", "\n".join([
        "# Platform Strategy",
        "",
        "\n".join(f"- {value['label']}: {value['guidance']}" for value in platform["platforms"].values()),
        "",
        "Manual upload workflow only.",
    ]))
    write_json(out / "clip_recommendations.json", {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "recommendations": recommendations,
    })
    return {
        "marketing_brief": relative_path(out / "marketing_brief.md", root),
        "market_attack_plan": relative_path(out / "market_attack_plan.md", root),
        "content_calendar": relative_path(out / "content_calendar.md", root),
        "platform_strategy": relative_path(out / "platform_strategy.md", root),
        "clip_recommendations": relative_path(out / "clip_recommendations.json", root),
    }


def import_instagram_insights(root: Path, input_path: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    analytics = root / "analytics"
    if not input_path:
        summary = {
            "version": 1,
            "updated_at": utc_now(),
            "local_only": True,
            "status": "guidance",
            "message": "Connect or import Instagram insights later. Marketing Studio can run on local clip data now.",
            "expected_fields": [
                "post_id", "platform", "caption", "date", "views", "reach", "likes", "comments",
                "shares", "saves", "watch_time", "retention", "profile_visits", "follows",
                "audience_age", "audience_gender", "audience_location"
            ],
            "dry_run": dry_run,
        }
        write_json(analytics / "instagram_insights_import.json", summary)
        write_json(analytics / "instagram_performance_summary.json", {"version": 1, "local_only": True, "records": 0, "status": "not_imported"})
        return summary

    source = input_path.resolve()
    records: list[dict[str, Any]] = []
    if source.suffix.lower() == ".json":
        payload = load_json(source, [])
        records = payload if isinstance(payload, list) else safe_list(payload.get("records"))
    elif source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            records = list(csv.DictReader(handle))
    else:
        raise ValueError("Instagram insights import supports .json or .csv files.")

    totals = Counter()
    for record in records:
        for key in ("views", "reach", "likes", "comments", "shares", "saves", "follows"):
            try:
                totals[key] += int(float(record.get(key) or 0))
            except (TypeError, ValueError):
                pass
    summary = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": "dry_run" if dry_run else "imported",
        "source": str(source),
        "records": len(records),
        "totals": dict(totals),
    }
    if not dry_run:
        write_json(analytics / "instagram_insights_import.json", {"records": records, **summary})
        write_json(analytics / "instagram_performance_summary.json", summary)
    else:
        write_json(analytics / "instagram_insights_import.json", summary)
    return summary
