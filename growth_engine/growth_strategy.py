from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .marketing_intelligence import PLATFORM_LABELS, PLATFORMS, load_json, safe_list, write_json, write_text


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _status(score: float) -> str:
    if score >= 82:
        return "strong"
    if score >= 62:
        return "promising"
    if score > 0:
        return "needs_attention"
    return "missing_data"


def _score_item(score: float, explanation: str, action: str) -> dict[str, Any]:
    return {
        "score": round(max(0.0, min(100.0, score)), 2),
        "status": _status(score),
        "explanation": explanation,
        "recommended_action": action,
    }


def _load_inputs(root: Path) -> dict[str, Any]:
    analytics = root / "analytics"
    return {
        "marketing_recommendations": load_json(analytics / "marketing_recommendations.json", {}),
        "campaign_board": load_json(analytics / "campaign_board.json", {}),
        "posting_schedule": load_json(analytics / "posting_schedule.json", {}),
        "performance_feedback": load_json(analytics / "performance_feedback.json", {}),
        "campaign_performance_summary": load_json(analytics / "campaign_performance_summary.json", {}),
        "marketing_learning_loop": load_json(analytics / "marketing_learning_loop.json", {}),
        "next_iteration_plan": load_json(analytics / "next_iteration_plan.json", {}),
        "client_campaign_plan": load_json(analytics / "client_campaign_plan.json", {}),
        "manual_post_status": load_json(analytics / "manual_post_status.json", {}),
        "performance_history": load_json(analytics / "performance_history.json", {}),
        "instagram_performance_summary": load_json(analytics / "instagram_performance_summary.json", {}),
        "approved_reviews": load_json(root / "queue" / "approved_reviews.json", {}),
        "social_manifest": load_json(root / "out" / "social_exports" / "manifest.json", {}),
        "marketing_profile": load_json(root / "config" / "marketing_profile.json", None)
        or load_json(root / "config" / "marketing_profile.example.json", {}),
    }


def _cards(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["campaign_board"].get("cards")) if isinstance(item, dict)]


def _recommendations(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["marketing_recommendations"].get("recommendations")) if isinstance(item, dict)]


def _feedback(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["performance_feedback"].get("records")) if isinstance(item, dict)]


def _approved_ids(data: dict[str, Any]) -> set[str]:
    payload = data.get("approved_reviews") or {}
    approved: set[str] = set()
    for key in ("approved_clip_ids", "approved_entry_ids"):
        approved.update(str(value) for value in safe_list(payload.get(key)))
    for item in safe_list(payload.get("approved")):
        if isinstance(item, str):
            approved.add(item)
        elif isinstance(item, dict):
            approved.update(str(item[key]) for key in ("id", "entry_id", "queue_id", "clip_id") if item.get(key))
    return approved


def _exported_clip_ids(data: dict[str, Any]) -> set[str]:
    return {str(item.get("clip_id")) for item in safe_list(data["social_manifest"].get("exports")) if isinstance(item, dict) and item.get("clip_id")}


def build_scorecard(data: dict[str, Any]) -> dict[str, Any]:
    recs = _recommendations(data)
    cards = _cards(data)
    feedback = _feedback(data)
    approved = _approved_ids(data)
    exported = _exported_clip_ids(data)
    seven_day = safe_list(data["posting_schedule"].get("seven_day_schedule"))
    learning = data["marketing_learning_loop"] if isinstance(data["marketing_learning_loop"], dict) else {}
    platforms = {card.get("platform") for card in cards if card.get("platform")}
    audiences = {card.get("audience") for card in cards if card.get("audience")}
    content = min(100, len(recs) * 8 + len(approved) * 10)
    campaign = min(100, len(cards) * 7 + len(seven_day) * 4)
    export = min(100, len(exported) * 20)
    learning_score = min(100, len(feedback) * 35)
    platform = min(100, len(platforms) * 18 + (20 if learning.get("strong_platforms") else 0))
    audience = min(100, len(audiences) * 18 + (20 if learning.get("winning_audience_segments") else 0))
    next_action = 90 if cards or seven_day else 35
    overall = _avg([content, campaign, export, learning_score, platform, audience, next_action])
    return {
        "overall_growth_score": _score_item(overall, "Composite growth readiness across content, campaign, export, learning, platform, audience, and next actions.", "Execute the ranked next best actions."),
        "content_readiness_score": _score_item(content, "Approved and high-scoring clip supply.", "Approve more strong clips if this is below promising."),
        "campaign_readiness_score": _score_item(campaign, "Campaign board and posting schedule completeness.", "Build or refresh the campaign plan."),
        "export_readiness_score": _score_item(export, "Manual-upload social packs available.", "Export packs for approved clips."),
        "performance_learning_score": _score_item(learning_score, "Manual post results recorded.", "Record results after each manual upload."),
        "platform_focus_score": _score_item(platform, "Clear platform focus from schedule and feedback.", "Double down on the strongest platform and keep one experiment lane."),
        "audience_clarity_score": _score_item(audience, "Audience fit from campaigns and feedback.", "Use winning audience language in hooks and captions."),
        "next_action_clarity_score": _score_item(next_action, "How clear the next growth move is.", "Execute the first next best action."),
    }


def build_content_pillars(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _cards(data)
    recs = _recommendations(data)
    feedback = _feedback(data)
    approved = _approved_ids(data)
    exported = _exported_clip_ids(data)
    actual_by_clip = {item.get("clip_id"): _num(item.get("overall_actual_score")) for item in feedback}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in cards or recs:
        grouped[str(item.get("content_pillar") or item.get("campaign_role") or "proof")].append(item)
    results = []
    for pillar, items in grouped.items():
        clip_ids = [str(item.get("clip_id")) for item in items if item.get("clip_id")]
        actuals = [actual_by_clip[clip_id] for clip_id in clip_ids if clip_id in actual_by_clip]
        avg_score = _avg([_num(item.get("score") or item.get("confidence") or item.get("confidence_score")) for item in items])
        avg_actual = _avg(actuals)
        if avg_actual >= 75 or avg_score >= 85:
            recommendation = "double_down"
        elif actuals and avg_actual < 50:
            recommendation = "pause"
        elif len(items) >= 2:
            recommendation = "test_more"
        else:
            recommendation = "needs_data"
        results.append({
            "pillar": pillar,
            "clip_count": len(clip_ids),
            "approved_count": len([clip_id for clip_id in clip_ids if clip_id in approved]),
            "exported_count": len([clip_id for clip_id in clip_ids if clip_id in exported]),
            "posted_count": len(actuals),
            "average_score": avg_score,
            "average_actual_performance": avg_actual if actuals else None,
            "recommendation": recommendation,
        })
    return sorted(results, key=lambda item: (item["recommendation"] == "double_down", item["average_actual_performance"] or item["average_score"]), reverse=True)


def build_platform_focus(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _cards(data)
    schedule = safe_list(data["posting_schedule"].get("seven_day_schedule"))
    feedback = _feedback(data)
    exports = safe_list(data["social_manifest"].get("exports"))
    posted = Counter(str(item.get("platform") or "").lower() for item in feedback)
    actuals: dict[str, list[float]] = defaultdict(list)
    for item in feedback:
        actuals[str(item.get("platform") or "").lower()].append(_num(item.get("overall_actual_score")))
    scheduled = Counter(str(item.get("platform") or item.get("platform_key") or "").lower().replace(" ", "_") for item in schedule)
    ready = Counter(str(item.get("platform") or item.get("platform_key") or "").lower() for item in exports if isinstance(item, dict))
    predicted: dict[str, list[float]] = defaultdict(list)
    for card in cards:
        predicted[str(card.get("platform") or "").lower()].append(_num(card.get("confidence") or card.get("score")))
    rows = []
    for platform in PLATFORMS:
        actual = _avg(actuals.get(platform, []))
        avg_predicted = _avg(predicted.get(platform, []))
        if actual >= 75 or (avg_predicted >= 85 and ready.get(platform, 0)):
            recommendation = "primary_focus"
        elif ready.get(platform, 0) or scheduled.get(platform, 0):
            recommendation = "secondary_focus"
        elif avg_predicted:
            recommendation = "experiment"
        else:
            recommendation = "hold"
        rows.append({
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "ready_pack_count": ready.get(platform, 0),
            "scheduled_posts": scheduled.get(platform, 0),
            "posted_count": posted.get(platform, 0),
            "average_predicted_score": avg_predicted,
            "actual_performance": actual if actuals.get(platform) else None,
            "manual_upload_status": "manual_upload_only",
            "recommendation": recommendation,
        })
    return rows


def build_audience_insights(data: dict[str, Any]) -> dict[str, Any]:
    profile = data["marketing_profile"] if isinstance(data["marketing_profile"], dict) else {}
    cards = _cards(data)
    learning = data["marketing_learning_loop"] if isinstance(data["marketing_learning_loop"], dict) else {}
    segments = Counter(str(card.get("audience") or "local audience") for card in cards)
    psychographics = profile.get("psychographics", {}) if isinstance(profile.get("psychographics"), dict) else {}
    return {
        "winning_audience_segments": safe_list(learning.get("winning_audience_segments")) or [item for item, _ in segments.most_common(3)] or ["needs data"],
        "likely_demographics": profile.get("demographics", {}),
        "psychographic_motivations": safe_list(psychographics.get("motivations")) or ["growth", "confidence", "momentum"],
        "objections_to_attack": safe_list(psychographics.get("objections")) or safe_list(psychographics.get("fears")) or ["not sure where to start"],
        "best_ctas": safe_list(learning.get("winning_ctas")) or ["Save this and start today."],
        "best_hooks": safe_list(learning.get("winning_hooks")) or [card.get("hook") for card in cards[:5] if card.get("hook")],
        "underperforming_audience_assumptions": ["Audience assumptions need more manual result data."] if not _feedback(data) else safe_list(learning.get("post_less_of")),
        "audience_test_ideas": [
            "Post the same hook to a creator-focused caption and a buyer-focused caption.",
            "Test proof-first wording against simple next-step wording.",
            "Compare save CTA against comment CTA after manual upload.",
        ],
    }


def build_experiments(data: dict[str, Any], pillars: list[dict[str, Any]], platforms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = _cards(data)
    top_clips = [card.get("clip_id") for card in cards[:3] if card.get("clip_id")] or ["next approved clip"]
    primary_platform = next((item["platform"] for item in platforms if item["recommendation"] == "primary_focus"), "tiktok")
    top_pillar = pillars[0]["pillar"] if pillars else "proof"
    templates = [
        ("hook_timing", "Opening with the hook in the first second will improve retention.", "retention", "60%"),
        ("caption_length", "Shorter captions will improve saves and shares.", "save_rate", "1.5%"),
        ("cta_style", "Direct save CTA will outperform broad engagement CTA.", "save_rate", "1.5%"),
        ("platform_split", "The same clip will perform best on the current primary focus platform.", "overall_actual_score", "70"),
        ("content_pillar", f"{top_pillar} clips will outperform mixed-topic clips.", "overall_actual_score", "72"),
        ("posting_sequence", "Proof before conversion will lift follow conversion.", "follow_conversion_rate", "5%"),
        ("thumbnail_style", "Readable thumbnails will increase profile visits.", "profile_visits", "10"),
    ]
    return [
        {
            "experiment_id": f"growth_exp_{index + 1}_{key}",
            "hypothesis": hypothesis,
            "clips_to_use": top_clips,
            "platform": primary_platform,
            "metric_to_watch": metric,
            "success_threshold": threshold,
            "duration": "7 days",
            "next_step_if_wins": "Make this pattern part of the next campaign sequence.",
            "next_step_if_loses": "Revise the hook, CTA, or platform fit and test again.",
        }
        for index, (key, hypothesis, metric, threshold) in enumerate(templates)
    ]


def build_next_actions(data: dict[str, Any], pillars: list[dict[str, Any]], platforms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = _cards(data)
    feedback = _feedback(data)
    approved = _approved_ids(data)
    exported = _exported_clip_ids(data)
    primary = next((item for item in platforms if item["recommendation"] == "primary_focus"), platforms[0] if platforms else {})
    top_card = cards[0] if cards else {}
    top_pillar = pillars[0] if pillars else {}
    actions: list[dict[str, Any]] = []

    def add(action_id: str, title: str, priority: int, why: str, effort: str, impact: str, **extra: Any) -> None:
        actions.append({"action_id": action_id, "title": title, "priority": priority, "why_it_matters": why, "effort": effort, "expected_impact": impact, "status": "open", **extra})

    if len(approved) < 3:
        add("approve_more_clips", "Approve 3 more high-scoring clips.", 95, "The growth plan needs more ready clips to sequence.", "medium", "More campaign options and stronger posting consistency.")
    if len(exported) < max(1, len(approved)):
        add("export_social_packs", "Export social packs for approved clips.", 90, "Prepared folders make manual upload faster.", "low", "Faster posting and cleaner handoff.", linked_platform=primary.get("platform"))
    if top_card:
        add("post_best_hook", "Post the best hook clip first.", 88, "Early-hook clips are the fastest learning signal.", "low", "Immediate performance feedback.", linked_clip_id=top_card.get("clip_id"), linked_platform=top_card.get("platform"), linked_campaign=top_card.get("campaign_role"))
    if not feedback:
        add("record_results", "Record results after manual upload.", 86, "Actual data improves future campaign recommendations.", "low", "Turns the plan into a learning loop.")
    if top_pillar:
        add("double_down_pillar", f"Double down on {top_pillar.get('pillar')} content.", 78, "This pillar has the strongest current signal.", "medium", "Clearer audience positioning.")
    add("test_caption", "Test shorter captions on Reels.", 65, "Caption clarity can improve saves and shares.", "low", "Cleaner CTA signal.", linked_platform="instagram_reels")
    add("import_more_hooks", "Import more footage with talking-head hooks.", 55, "Fresh hook styles give the strategy more range.", "medium", "More experiments and better creative coverage.")
    return sorted(actions, key=lambda item: item["priority"], reverse=True)


def write_growth_markdown(root: Path, strategy: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    scorecard = strategy["scorecard"]
    actions = strategy["next_best_actions"]
    pillars = strategy["content_pillar_performance"]
    platforms = strategy["platform_focus"]
    experiments = strategy["growth_experiments"]
    write_text(out / "growth_strategy.md", "\n".join(["# Growth Strategy", "", f"Overall growth score: {scorecard['overall_growth_score']['score']} ({scorecard['overall_growth_score']['status']})", "", "## What To Do Next", *[f"- {item['title']} ({item['expected_impact']})" for item in actions[:7]], "", "Manual upload only. No live platform or direct posting integrations are configured."]))
    write_text(out / "next_best_actions.md", "\n".join(["# Next Best Actions", "", *[f"{idx + 1}. {item['title']} - {item['why_it_matters']}" for idx, item in enumerate(actions)]]))
    write_text(out / "growth_scorecard.md", "\n".join(["# Growth Scorecard", "", *[f"- {key}: {value['score']} ({value['status']}) - {value['recommended_action']}" for key, value in scorecard.items()]]))
    write_text(out / "content_pillar_performance.md", "\n".join(["# Content Pillar Performance", "", *[f"- {item['pillar']}: {item['recommendation']} ({item['clip_count']} clips)" for item in pillars]]))
    write_text(out / "platform_focus.md", "\n".join(["# Platform Focus", "", *[f"- {item['platform_label']}: {item['recommendation']} ({item['ready_pack_count']} ready packs)" for item in platforms]]))
    write_text(out / "growth_experiments.md", "\n".join(["# Growth Experiments", "", *[f"- {item['hypothesis']} Watch: {item['metric_to_watch']}." for item in experiments]]))
    return {key: relative_path(out / f"{key}.md", root) for key in ("growth_strategy", "next_best_actions", "growth_scorecard", "content_pillar_performance", "platform_focus", "growth_experiments")}


def build_growth_strategy(root: Path, days: int = 30, dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    data = _load_inputs(project_root)
    scorecard = build_scorecard(data)
    pillars = build_content_pillars(data)
    platforms = build_platform_focus(data)
    audience = build_audience_insights(data)
    experiments = build_experiments(data, pillars, platforms)
    actions = build_next_actions(data, pillars, platforms)
    seven_day = safe_list(data["posting_schedule"].get("seven_day_schedule"))[:7]
    primary = next((item for item in platforms if item["recommendation"] == "primary_focus"), platforms[0] if platforms else {})
    best_pillar = pillars[0] if pillars else {}
    strategy = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "growth_score": scorecard["overall_growth_score"],
        "scorecard": scorecard,
        "next_best_actions": actions,
        "content_pillar_performance": pillars,
        "platform_focus": platforms,
        "audience_growth_insights": audience,
        "growth_experiments": experiments,
        "next_7_day_growth_plan": seven_day,
        "primary_platform": primary,
        "best_content_pillar": best_pillar,
        "needs_data": scorecard["performance_learning_score"]["status"] == "missing_data",
        "confidence": "needs performance data" if not _feedback(data) else "performance-informed",
    }
    dashboard = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "cards": {
            "growth_score": scorecard["overall_growth_score"],
            "next_best_action": actions[0] if actions else None,
            "primary_platform": primary,
            "winning_audience": (audience.get("winning_audience_segments") or ["needs data"])[0],
            "best_content_pillar": best_pillar,
            "needs_data": strategy["needs_data"],
        },
        "strategy": strategy,
    }
    client_plan = {
        "version": 1,
        "updated_at": utc_now(),
        "status": "ready" if actions else "needs_input",
        "local_only": True,
        "manual_upload_only": True,
        "message": "Growth strategy ready. Execute the next best action and record results after manual upload.",
        "next_action": actions[0] if actions else None,
        "next_7_days": seven_day,
        "primary_platform": primary,
        "best_content_pillar": best_pillar,
        "confidence": strategy["confidence"],
    }
    markdown = {} if dry_run else write_growth_markdown(project_root, strategy)
    if not dry_run:
        analytics = project_root / "analytics"
        write_json(analytics / "growth_strategy.json", strategy)
        write_json(analytics / "growth_dashboard.json", dashboard)
        write_json(analytics / "growth_scorecard.json", {"local_only": True, **scorecard})
        write_json(analytics / "next_best_actions.json", {"version": 1, "updated_at": utc_now(), "local_only": True, "actions": actions})
        write_json(analytics / "content_pillar_performance.json", {"version": 1, "updated_at": utc_now(), "local_only": True, "pillars": pillars})
        write_json(analytics / "platform_focus.json", {"version": 1, "updated_at": utc_now(), "local_only": True, "platforms": platforms})
        write_json(analytics / "audience_growth_insights.json", {"version": 1, "updated_at": utc_now(), "local_only": True, **audience})
        write_json(analytics / "growth_experiments.json", {"version": 1, "updated_at": utc_now(), "local_only": True, "experiments": experiments})
        write_json(analytics / "client_growth_plan.json", client_plan)
    return {"ok": True, "dry_run": dry_run, "local_only": True, "manual_upload_only": True, "direct_posting_apis": False, "growth_score": scorecard["overall_growth_score"]["score"], "next_actions": len(actions), "experiments": len(experiments), "markdown_outputs": markdown}
