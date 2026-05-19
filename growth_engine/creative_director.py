from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .marketing_intelligence import PLATFORM_LABELS, PLATFORMS, load_json, safe_list, write_json, write_text


HOOK_STYLES = ("direct", "emotional", "curiosity", "proof", "challenge", "identity", "contrarian", "story", "tutorial", "callout")
CAPTION_STYLES = ("short", "story", "direct_cta", "save_share", "comment_bait", "professional", "bold_edgy")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def _items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            values = safe_list(payload.get(key))
            if values:
                return [item for item in values if isinstance(item, dict)]
    return []


def _load_profile(root: Path) -> dict[str, Any]:
    return load_json(root / "config" / "marketing_profile.json", None) or load_json(root / "config" / "marketing_profile.example.json", {})


def _load_inputs(root: Path) -> dict[str, Any]:
    analytics = root / "analytics"
    paths = {
        "growth_strategy": analytics / "growth_strategy.json",
        "growth_dashboard": analytics / "growth_dashboard.json",
        "next_best_actions": analytics / "next_best_actions.json",
        "marketing_recommendations": analytics / "marketing_recommendations.json",
        "campaign_board": analytics / "campaign_board.json",
        "posting_schedule": analytics / "posting_schedule.json",
        "performance_feedback": analytics / "performance_feedback.json",
        "marketing_learning_loop": analytics / "marketing_learning_loop.json",
        "client_campaign_plan": analytics / "client_campaign_plan.json",
        "approved_reviews": root / "queue" / "approved_reviews.json",
        "color_school": analytics / "color_school_report.json",
        "audio_school": analytics / "audio_school_report.json",
        "media_cache": analytics / "media_cache.json",
        "social_manifest": root / "out" / "social_exports" / "manifest.json",
        "marketing_profile": root / "config" / "marketing_profile.json",
        "marketing_profile_example": root / "config" / "marketing_profile.example.json",
    }
    data = {name: load_json(path, {}) for name, path in paths.items() if name not in {"marketing_profile", "marketing_profile_example"}}
    data["marketing_profile"] = _load_profile(root)
    data["source_files"] = [relative_path(path, root) for path in paths.values() if path.exists()]
    return data


def _approved_ids(data: dict[str, Any]) -> set[str]:
    payload = data.get("approved_reviews") if isinstance(data.get("approved_reviews"), dict) else {}
    approved: set[str] = set()
    for key in ("approved_clip_ids", "approved_entry_ids"):
        approved.update(str(value) for value in safe_list(payload.get(key)))
    for item in safe_list(payload.get("approved")):
        if isinstance(item, str):
            approved.add(item)
        elif isinstance(item, dict):
            approved.update(str(item[key]) for key in ("id", "entry_id", "queue_id", "clip_id") if item.get(key))
    return approved


def _export_folders(data: dict[str, Any]) -> dict[str, list[str]]:
    folders: dict[str, list[str]] = {}
    for item in _items(data.get("social_manifest"), "exports", "items"):
        clip_id = item.get("clip_id")
        folder = item.get("output_dir") or item.get("folder") or item.get("path")
        if clip_id and folder:
            folders.setdefault(str(clip_id), []).append(str(folder))
    return folders


def _scorecard_by_clip(payload: Any) -> dict[str, dict[str, Any]]:
    return {str(item.get("clip_id")): item for item in _items(payload, "clips", "results", "items") if item.get("clip_id")}


def _clip_pool(data: dict[str, Any], clip_id: str | None = None, platform: str | None = None) -> list[dict[str, Any]]:
    approved = _approved_ids(data)
    recs = _items(data.get("marketing_recommendations"), "recommendations")
    cards = _items(data.get("campaign_board"), "cards")
    by_clip: dict[str, dict[str, Any]] = {}
    for item in recs + cards:
        cid = item.get("clip_id")
        if not cid:
            continue
        by_clip.setdefault(str(cid), {}).update({k: v for k, v in item.items() if v not in (None, "", [])})
    pool = [row for cid, row in by_clip.items() if not approved or cid in approved or row.get("queue_entry_id") in approved]
    if clip_id:
        pool = [row for row in pool if row.get("clip_id") == clip_id]
    if platform:
        target = platform.lower().replace(" ", "_")
        pool = [row for row in pool if str(row.get("platform") or row.get("best_platform") or "").lower().replace(" ", "_") == target]
    if not pool:
        pool = recs[:8] or cards[:8] or [{
            "clip_id": clip_id or "next_clip",
            "title": "Next strong clip",
            "hook": "Drop footage. HigherKey finds the moments.",
            "audience": "high-intent creators",
            "platform": platform or "tiktok",
            "campaign_role": "awareness",
            "content_pillar": "proof",
            "score": 0,
            "recommended_cta": "Save this and start today.",
        }]
    color = _scorecard_by_clip(data.get("color_school"))
    audio = _scorecard_by_clip(data.get("audio_school"))
    exports = _export_folders(data)
    for row in pool:
        cid = str(row.get("clip_id") or "")
        row.setdefault("title", row.get("hook") or cid or "Creative clip")
        row.setdefault("hook", row.get("attack_angle") or row.get("title") or "Lead with the strongest moment.")
        row.setdefault("audience", "high-intent creators")
        row.setdefault("platform", row.get("best_platform") or "tiktok")
        row.setdefault("platform_label", PLATFORM_LABELS.get(row.get("platform"), row.get("platform", "TikTok")))
        row.setdefault("campaign_role", "awareness")
        row.setdefault("content_pillar", row.get("campaign_role") or "proof")
        row.setdefault("recommended_cta", row.get("best_cta") or row.get("CTA") or "Save this and start today.")
        row["color_readiness"] = color.get(cid, {}).get("score") or color.get(cid, {}).get("color_readiness")
        row["audio_readiness"] = audio.get(cid, {}).get("score") or audio.get(cid, {}).get("audio_readiness")
        row["export_folders"] = exports.get(cid, [])
    return sorted(pool, key=lambda item: _num(item.get("score") or item.get("confidence") or item.get("confidence_score")), reverse=True)


def _dominant(values: list[str], fallback: str) -> str:
    clean = [value for value in values if value]
    return Counter(clean).most_common(1)[0][0] if clean else fallback


def _best_hook_style(data: dict[str, Any], clips: list[dict[str, Any]]) -> str:
    learning = data.get("marketing_learning_loop") if isinstance(data.get("marketing_learning_loop"), dict) else {}
    text = " ".join(str(item) for item in safe_list(learning.get("winning_hooks"))).lower()
    if "proof" in text or "result" in text:
        return "proof"
    if "you" in text or "creator" in text or "operator" in text:
        return "callout"
    if clips and _num(clips[0].get("score") or clips[0].get("confidence")) >= 85:
        return "direct"
    return "curiosity"


def _base_payload(**extra: Any) -> dict[str, Any]:
    return {
        "version": "V5.5",
        "generated_at": utc_now(),
        "local_only": True,
        "local_first": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        **extra,
    }


def build_creative_brief(data: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, Any]:
    profile = data.get("marketing_profile") if isinstance(data.get("marketing_profile"), dict) else {}
    growth = data.get("growth_strategy") if isinstance(data.get("growth_strategy"), dict) else {}
    top = clips[0] if clips else {}
    primary_audience = _dominant([str(item.get("audience") or "") for item in clips], "high-intent creators")
    primary_platform = _dominant([str(item.get("platform") or item.get("best_platform") or "") for item in clips], "tiktok")
    primary_pillar = _dominant([str(item.get("content_pillar") or item.get("campaign_role") or "") for item in clips], "proof")
    thesis = growth.get("strategy_summary") or f"Lead with {primary_pillar} clips for {primary_audience}."
    return _base_payload(
        campaign_creative_thesis=thesis,
        best_creative_angle=top.get("attack_angle") or top.get("hook") or "Make the next move feel simple and worth saving.",
        tone=profile.get("brand_voice") or "confident, useful, cinematic",
        visual_direction="Graphite, high contrast, mobile-readable, and focused on the strongest hook frame.",
        hook_strategy=f"Open with a {_best_hook_style(data, clips)} hook in the first three seconds.",
        caption_strategy="Use short captions for discovery, story captions for trust, and direct CTA captions when packs are ready.",
        CTA_strategy=top.get("recommended_cta") or top.get("best_cta") or profile.get("call_to_action_style") or "Save this and start today.",
        thumbnail_strategy="Use a high-contrast frame, one emotion, and three to five words that state the payoff.",
        suggested_sequence=["Post the strongest hook first.", "Follow with proof or process within 48 hours.", "Record manual results and keep the winning hook style."],
        what_to_avoid=["Long setup before payoff.", "Generic captions with no next step.", "Low-contrast thumbnails.", "Posting without recording manual results."],
        next_creative_move=f"Build the next post around {top.get('title', 'the strongest approved clip')} for {primary_audience}.",
        primary_audience=primary_audience,
        primary_platform=primary_platform,
        primary_content_pillar=primary_pillar,
    )


def build_hook_bank(data: dict[str, Any], clips: list[dict[str, Any]], count: int) -> dict[str, Any]:
    templates = {
        "direct": "Here is the moment that makes this worth posting.",
        "emotional": "This is the part people feel before they understand it.",
        "curiosity": "Most people miss this moment in the first five seconds.",
        "proof": "This clip proves the idea faster than explaining it.",
        "challenge": "Try watching this without wanting the next step.",
        "identity": "If you are building something serious, this is the signal.",
        "contrarian": "The strongest post is not always the loudest clip.",
        "story": "This is where the story turns.",
        "tutorial": "Use this clip as the first move in the sequence.",
        "callout": "Creators who want momentum should start here.",
    }
    hooks = []
    for index in range(max(1, count)):
        style = HOOK_STYLES[index % len(HOOK_STYLES)]
        clip = clips[index % len(clips)]
        platform = str(clip.get("platform") or "tiktok")
        hooks.append({
            "hook_id": f"hook_{index + 1:02d}",
            "text": templates[style] if index < len(HOOK_STYLES) else str(clip.get("hook") or templates[style]),
            "style": style,
            "target_audience": clip.get("audience") or "high-intent creators",
            "platform_fit": PLATFORM_LABELS.get(platform, platform),
            "campaign_role": clip.get("campaign_role") or "awareness",
            "recommended_clip_id": clip.get("clip_id"),
            "why_it_works": f"{style.replace('_', ' ').title()} hooks give the audience a clear reason to stop scrolling.",
        })
    return _base_payload(hooks=hooks)


def build_caption_variations(clips: list[dict[str, Any]]) -> dict[str, Any]:
    captions = []
    for clip in clips:
        clip_id = str(clip.get("clip_id") or "clip")
        platform = str(clip.get("platform") or "tiktok")
        hook = clip.get("hook") or clip.get("title") or "This is the moment."
        cta = clip.get("recommended_cta") or "Save this and start today."
        variants = {
            "short": f"{hook} {cta}",
            "story": f"This works because the viewer gets the turn before the explanation. {cta}",
            "direct_cta": f"Use this as your next move. {cta}",
            "save_share": "Save this for the next time you need a stronger post. Share it with someone building momentum.",
            "comment_bait": "Which moment would you post first? Comment the frame that caught you.",
            "professional": f"A clear hook, fast proof, and a simple next step. {cta}",
            "bold_edgy": f"Stop overthinking the edit. Post the moment that already works. {cta}",
        }
        for style in CAPTION_STYLES:
            captions.append({"caption_id": f"{clip_id}_{style}", "clip_id": clip_id, "platform": platform, "text": variants[style], "CTA": cta, "tone": style, "recommended_hashtags": ["#shortform", "#creator", "#growth"], "notes": "Review before manual upload."})
    return _base_payload(captions=captions)


def build_thumbnail_concepts(clips: list[dict[str, Any]]) -> dict[str, Any]:
    concepts = []
    for clip in clips:
        clip_id = str(clip.get("clip_id") or "clip")
        platform = str(clip.get("platform") or "tiktok")
        concepts.append({"thumbnail_id": f"{clip_id}_{platform}_thumb_01", "clip_id": clip_id, "platform": platform, "visual_concept": "Freeze the highest-contrast hook frame with clear motion.", "text_overlay": "START HERE" if platform == "tiktok" else "THE MOMENT", "emotion": "confidence and forward motion", "framing_suggestion": "Tight mobile crop with central subject and clean overlay space.", "color_direction": "Keep red/graphite contrast readable on mobile.", "why_it_works": "The thumbnail states the payoff before playback."})
    return _base_payload(concepts=concepts)


def build_scripts_and_shots(data: dict[str, Any], clips: list[dict[str, Any]], count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = data.get("marketing_profile") if isinstance(data.get("marketing_profile"), dict) else {}
    pillars = safe_list(profile.get("content_pillars")) or ["proof", "process", "transformation", "education"]
    ideas, shots = [], []
    for index in range(max(3, count)):
        clip = clips[index % len(clips)]
        pillar = str(pillars[index % len(pillars)])
        platform = str(clip.get("platform") or PLATFORMS[index % len(PLATFORMS)])
        idea_id = f"script_{index + 1:02d}"
        shot_list = ["Talking-head hook.", "Close-up proof shot.", "Wide context shot.", "Final CTA frame."]
        ideas.append({"idea_id": idea_id, "title": f"{pillar.title()} follow-up", "audience": clip.get("audience") or "high-intent creators", "hook": f"Here is the {pillar} moment most people skip.", "script_outline": ["Name the problem.", "Show proof or process.", "Explain why it matters.", "Give one clear action."], "shot_list": shot_list, "CTA": clip.get("recommended_cta") or "Save this and start today.", "platform": platform, "content_pillar": pillar, "difficulty": "low" if index < 3 else "medium", "expected_impact": "high" if index < 3 else "medium"})
        shots.append({"idea_id": idea_id, "clip_id": clip.get("clip_id"), "recommendation": f"Shoot one pickup that makes the {pillar} claim visible.", "shots": shot_list, "missing_proof_shot": "A short proof insert would make the campaign easier to trust.", "b_roll_ideas": ["hands in motion", "screen close-up", "behind the scenes", "reaction shot"], "platform": platform, "expected_impact": "Improves trust and gives another hook option."})
    return _base_payload(ideas=ideas), _base_payload(shots=shots)


def build_ab_tests(clips: list[dict[str, Any]]) -> dict[str, Any]:
    tests = []
    seeds = [("hook_timing", "Start with payoff frame vs setup frame", "retention"), ("caption_length", "Short caption vs story caption", "saves"), ("cta_style", "Save CTA vs comment CTA", "saves"), ("platform_split", "TikTok first vs Instagram Reels first", "views"), ("thumbnail_text", "No text vs three-word payoff", "click-through proxy"), ("posting_order", "Proof clip first vs process clip first", "engagement"), ("content_pillar", "Proof pillar vs transformation pillar", "shares")]
    for index, (name, hypothesis, metric) in enumerate(seeds, start=1):
        clip = clips[(index - 1) % len(clips)]
        tests.append({"test_id": f"ab_{index:02d}_{name}", "hypothesis": hypothesis, "clip_ids": [clip.get("clip_id")], "variants": ["A", "B"], "platform": clip.get("platform") or "tiktok", "metric_to_watch": metric, "success_threshold": "10% lift over baseline", "duration": "7 days or 2 posts", "next_step_if_wins": "Use the winning variant in the next campaign sequence.", "next_step_if_loses": "Return to the stronger hook and test CTA only."})
    return _base_payload(tests=tests)


def build_quality_scorecard(brief: dict[str, Any], hooks: dict[str, Any], captions: dict[str, Any], thumbnails: dict[str, Any], scripts: dict[str, Any], tests: dict[str, Any]) -> dict[str, Any]:
    def item(score: int, reason: str, improvement: str) -> dict[str, Any]:
        return {"score": min(100, score), "status": "strong" if score >= 82 else "promising" if score >= 62 else "needs_attention", "reason": reason, "improvement": improvement}
    return _base_payload(
        hook_strength=item(len(safe_list(hooks.get("hooks"))) * 4, "Hook bank covers multiple styles.", "Record results to identify winning hook style."),
        caption_strength=item(len(safe_list(captions.get("captions"))) * 3, "Caption variants exist for approved/high-scoring clips.", "Choose one short and one story caption."),
        thumbnail_readiness=item(len(safe_list(thumbnails.get("concepts"))) * 18, "Thumbnail concepts are ready.", "Create visual thumbnails after platform winner emerges."),
        audience_fit=item(80 if brief.get("primary_audience") else 55, "Creative direction is tied to audience.", "Refine marketing profile for sharper segments."),
        CTA_clarity=item(78 if brief.get("CTA_strategy") else 50, "CTA strategy is explicit.", "Test save/share/comment CTAs."),
        platform_fit=item(78 if brief.get("primary_platform") else 50, "Platform direction is derived locally.", "Record results to improve platform confidence."),
        campaign_alignment=item(84 if brief.get("campaign_creative_thesis") else 55, "Creative thesis aligns to growth plan.", "Build campaign and growth plans before refreshing."),
        testing_readiness=item(len(safe_list(tests.get("tests"))) * 12, "A/B tests are ready to run manually.", "Pick one experiment per week."),
    )


def write_creative_markdown(root: Path, outputs: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    brief = outputs["creative_director_brief"]
    write_text(out / "creative_director_brief.md", "\n".join(["# Creative Director Brief", "", f"Creative thesis: {brief['campaign_creative_thesis']}", f"Best angle: {brief['best_creative_angle']}", f"Tone: {brief['tone']}", f"Hook strategy: {brief['hook_strategy']}", f"Caption strategy: {brief['caption_strategy']}", f"CTA strategy: {brief['CTA_strategy']}", f"Thumbnail strategy: {brief['thumbnail_strategy']}", "", "Manual upload only. No cloud, live social, or direct posting APIs are used."]))
    write_text(out / "hook_bank.md", "\n".join(["# Hook Bank", "", *[f"- [{item['style']}] {item['text']} ({item['platform_fit']})" for item in outputs["hook_bank"]["hooks"]]]))
    write_text(out / "caption_variations.md", "\n".join(["# Caption Variations", "", *[f"- {item['clip_id']} / {item['tone']}: {item['text']}" for item in outputs["caption_variations"]["captions"]]]))
    write_text(out / "thumbnail_concepts.md", "\n".join(["# Thumbnail Concepts", "", *[f"- {item['clip_id']} / {item['platform']}: {item['visual_concept']} | Text: {item['text_overlay']}" for item in outputs["thumbnail_concepts"]["concepts"]]]))
    write_text(out / "script_ideas.md", "\n".join(["# Script Ideas", "", *[f"- {item['title']}: {item['hook']} CTA: {item['CTA']}" for item in outputs["script_ideas"]["ideas"]]]))
    write_text(out / "shot_list_recommendations.md", "\n".join(["# Shot List Recommendations", "", *[f"- {item['recommendation']} ({item['platform']})" for item in outputs["shot_list_recommendations"]["shots"]]]))
    write_text(out / "ab_test_plan.md", "\n".join(["# A/B Test Plan", "", *[f"- {item['hypothesis']} | Watch: {item['metric_to_watch']} | Platform: {item['platform']}" for item in outputs["ab_test_plan"]["tests"]]]))
    return {name: relative_path(path, root) for name, path in {
        "creative_director_brief": out / "creative_director_brief.md",
        "hook_bank": out / "hook_bank.md",
        "caption_variations": out / "caption_variations.md",
        "thumbnail_concepts": out / "thumbnail_concepts.md",
        "script_ideas": out / "script_ideas.md",
        "shot_list_recommendations": out / "shot_list_recommendations.md",
        "ab_test_plan": out / "ab_test_plan.md",
    }.items()}


def build_creative_direction(root: Path, clip_id: str | None = None, platform: str | None = None, count: int = 20, dry_run: bool = False) -> dict[str, Any]:
    data = _load_inputs(root)
    clips = _clip_pool(data, clip_id=clip_id, platform=platform)
    hook_count = max(1, min(60, count))
    script_count = max(3, min(12, count // 2 if count > 6 else count))
    brief = build_creative_brief(data, clips)
    hooks = build_hook_bank(data, clips, hook_count)
    captions = build_caption_variations(clips)
    thumbnails = build_thumbnail_concepts(clips)
    scripts, shots = build_scripts_and_shots(data, clips, script_count)
    tests = build_ab_tests(clips)
    scorecard = build_quality_scorecard(brief, hooks, captions, thumbnails, scripts, tests)
    client = _base_payload(status="ready", message="Creative direction is ready. Pick one hook, one caption, and one manual A/B test.", next_creative_move=brief["next_creative_move"], best_hook_style=_best_hook_style(data, clips), caption_direction=brief["caption_strategy"], thumbnail_direction=brief["thumbnail_strategy"], next_script_idea=scripts["ideas"][0] if scripts["ideas"] else None, ab_test_ready=bool(tests["tests"]))
    outputs = {"creative_director_brief": brief, "hook_bank": hooks, "caption_variations": captions, "thumbnail_concepts": thumbnails, "script_ideas": scripts, "shot_list_recommendations": shots, "ab_test_plan": tests, "creative_quality_scorecard": scorecard, "client_creative_plan": client}
    markdown = write_creative_markdown(root, outputs) if not dry_run else {}
    if not dry_run:
        analytics = root / "analytics"
        for name, payload in outputs.items():
            write_json(analytics / f"{name}.json", payload)
    return {"ok": True, "version": "V5.5", "dry_run": dry_run, "local_only": True, "local_first": True, "manual_upload_only": True, "direct_posting_apis": False, "live_instagram_api": False, "clip_count": len(clips), "hook_count": len(hooks["hooks"]), "caption_count": len(captions["captions"]), "thumbnail_count": len(thumbnails["concepts"]), "script_count": len(scripts["ideas"]), "test_count": len(tests["tests"]), "outputs_written": not dry_run, "markdown_outputs": markdown, "source_files": data.get("source_files", []), "next_creative_move": client["next_creative_move"]}
