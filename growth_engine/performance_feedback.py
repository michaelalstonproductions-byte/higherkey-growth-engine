from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .marketing_intelligence import load_json, safe_list, write_json, write_text


def _key(platform: str, clip_id: str) -> str:
    return f"{platform.strip().lower()}:{clip_id}"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rate(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100.0, 3)


def normalize_retention_percent(value: Any) -> float:
    retention = _float(value)
    if retention <= 0:
        return 0.0
    if retention <= 1:
        retention *= 100.0
    return round(max(0.0, min(100.0, retention)), 3)


def _payload_items(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            items = safe_list(payload.get(key))
            if items:
                return items
    return []


def load_recommendations(root: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(root / "analytics" / "marketing_recommendations.json", {})
    recs = safe_list(payload.get("recommendations"))
    return {str(item.get("clip_id")): item for item in recs if isinstance(item, dict) and item.get("clip_id")}


def load_campaign_cards(root: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(root / "analytics" / "campaign_board.json", {})
    cards = safe_list(payload.get("cards"))
    keyed: dict[str, dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        clip_id = str(card.get("clip_id") or "")
        platform = str(card.get("platform") or "")
        if clip_id:
            keyed[_key(platform, clip_id)] = card
            keyed.setdefault(clip_id, card)
    return keyed


def load_performance_context(root: Path) -> dict[str, Any]:
    manual_status = load_json(root / "analytics" / "manual_post_status.json", {})
    schedule = load_json(root / "analytics" / "posting_schedule.json", {})
    approved = load_json(root / "queue" / "approved_reviews.json", {})
    manifest = load_json(root / "out" / "social_exports" / "manifest.json", {})
    return {
        "manual_post_status": manual_status,
        "posting_schedule": schedule,
        "approved_reviews": approved,
        "social_export_manifest": manifest,
    }


def load_manual_performance_history(root: Path) -> dict[str, Any]:
    payload = load_json(root / "analytics" / "performance_history.json", {})
    records = []
    for item in safe_list(payload.get("records")):
        if not isinstance(item, dict):
            continue
        if item.get("record_source") == "imported_summary" or str(item.get("record_id") or "").startswith("manual_import_"):
            continue
        normalized = dict(item)
        normalized["record_source"] = "manual"
        normalized["manual_entry"] = True
        if "retention_percent" not in normalized:
            normalized["retention_percent"] = normalize_retention_percent(normalized.get("retention"))
        normalized["retention"] = normalize_retention_percent(normalized.get("retention_percent"))
        records.append(normalized)
    return {
        "version": int(payload.get("version") or 1) if isinstance(payload, dict) else 1,
        "records": records,
    }


def load_imported_summary_records(root: Path) -> list[dict[str, Any]]:
    instagram = load_json(root / "analytics" / "instagram_performance_summary.json", {})
    instagram_records = safe_list(instagram.get("records") or instagram.get("posts") or instagram.get("items"))
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in instagram_records:
        if not isinstance(item, dict):
            continue
        clip_id = item.get("clip_id") or item.get("matched_clip_id") or item.get("post_id")
        platform = item.get("platform") or "instagram_reels"
        if not clip_id:
            continue
        record_id = f"summary_import_{platform}_{clip_id}_{item.get('date') or item.get('posted_at') or ''}"
        if record_id in seen:
            continue
        seen.add(record_id)
        retention_percent = normalize_retention_percent(item.get("retention_percent", item.get("retention")))
        records.append({
            "record_id": record_id,
            "record_source": "imported_summary",
            "manual_entry": False,
            "clip_id": clip_id,
            "platform": platform,
            "posted_at": item.get("date") or item.get("posted_at"),
            "views": item.get("views") or item.get("reach"),
            "likes": item.get("likes"),
            "comments": item.get("comments"),
            "shares": item.get("shares"),
            "saves": item.get("saves"),
            "watch_time": item.get("watch_time"),
            "retention": retention_percent,
            "retention_percent": retention_percent,
            "profile_visits": item.get("profile_visits"),
            "follows": item.get("follows"),
            "notes": "Manual Instagram insights import.",
        })
    return records


def load_performance_history(root: Path) -> dict[str, Any]:
    manual = load_manual_performance_history(root)
    imported = load_imported_summary_records(root)
    return {
        "version": manual["version"],
        "records": manual["records"] + imported,
        "manual_records": manual["records"],
        "imported_summary_records": imported,
    }


def score_record(record: dict[str, Any], rec: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    views = _float(record.get("views"))
    likes = _float(record.get("likes"))
    comments = _float(record.get("comments"))
    shares = _float(record.get("shares"))
    saves = _float(record.get("saves"))
    profile_visits = _float(record.get("profile_visits"))
    follows = _float(record.get("follows"))
    retention = normalize_retention_percent(record.get("retention_percent", record.get("retention")))
    engagement = likes + comments + shares + saves
    engagement_rate = _rate(engagement, views)
    save_rate = _rate(saves, views)
    share_rate = _rate(shares, views)
    comment_rate = _rate(comments, views)
    follow_conversion_rate = _rate(follows, profile_visits)
    retention_score = max(0.0, min(100.0, retention))
    actual = min(
        100.0,
        round(
            engagement_rate * 3.2
            + save_rate * 5.0
            + share_rate * 4.0
            + comment_rate * 2.5
            + follow_conversion_rate * 0.8
            + retention_score * 0.35,
            2,
        ),
    )
    predicted = _float(rec.get("confidence_score") or card.get("confidence") or rec.get("score") or card.get("score"))
    delta = round(actual - predicted, 2)
    worked: list[str] = []
    weak: list[str] = []
    if engagement_rate >= 8:
        worked.append("Strong engagement rate for the audience.")
    else:
        weak.append("Engagement was below the expected signal.")
    if save_rate >= 1.5:
        worked.append("Saves indicate the post had repeat-value.")
    else:
        weak.append("Save rate was soft; make the takeaway more useful.")
    if share_rate >= 0.8:
        worked.append("Share behavior suggests the hook traveled.")
    if retention_score >= 60:
        worked.append("Retention held attention long enough to keep testing this angle.")
    else:
        weak.append("Retention was light; tighten the first three seconds.")
    if delta >= 5:
        adjustment = "Double down on this audience, hook, and CTA pattern."
    elif delta <= -10:
        adjustment = "Revise the hook, shorten the setup, and test a clearer CTA."
    else:
        adjustment = "Keep testing with small caption and platform timing variations."
    return {
        "clip_id": record.get("clip_id"),
        "platform": record.get("platform") or "unknown",
        "posted_at": record.get("posted_at"),
        "metrics": {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "watch_time": _float(record.get("watch_time")),
            "retention": retention,
            "retention_percent": retention,
            "profile_visits": profile_visits,
            "follows": follows,
        },
        "engagement_rate": engagement_rate,
        "save_rate": save_rate,
        "share_rate": share_rate,
        "comment_rate": comment_rate,
        "follow_conversion_rate": follow_conversion_rate,
        "retention_score": retention_score,
        "predicted_score": predicted,
        "overall_actual_score": actual,
        "expected_vs_actual_delta": delta,
        "audience": rec.get("audience") or card.get("audience") or "local audience",
        "hook": rec.get("hook") or card.get("hook") or "strongest moment",
        "CTA": rec.get("recommended_cta") or rec.get("best_cta") or card.get("CTA") or "Save this and start today.",
        "campaign_role": rec.get("campaign_role") or card.get("campaign_role") or "awareness",
        "content_pillar": card.get("content_pillar") or rec.get("campaign_role") or "proof",
        "what_worked": worked or ["The post produced a measurable baseline."],
        "what_underperformed": weak,
        "recommended_next_adjustment": adjustment,
        "notes": record.get("notes") or "",
        "record_source": record.get("record_source") or "manual",
    }


def summarize_feedback(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "status": "needs_input",
            "posted_count": 0,
            "best_platforms": [],
            "winning_hooks": [],
            "winning_ctas": [],
            "message": "Record manual post results to activate the learning loop.",
        }
    sorted_records = sorted(records, key=lambda item: _float(item.get("overall_actual_score")), reverse=True)
    best = sorted_records[0]
    platform_scores: dict[str, list[float]] = {}
    pillar_scores: dict[str, list[float]] = {}
    role_scores: dict[str, list[float]] = {}
    for item in records:
        platform_scores.setdefault(str(item.get("platform") or "unknown"), []).append(_float(item.get("overall_actual_score")))
        pillar_scores.setdefault(str(item.get("content_pillar") or "unknown"), []).append(_float(item.get("overall_actual_score")))
        role_scores.setdefault(str(item.get("campaign_role") or "unknown"), []).append(_float(item.get("overall_actual_score")))

    def rank(values: dict[str, list[float]]) -> list[dict[str, Any]]:
        return [
            {"name": key, "average_score": round(sum(scores) / max(1, len(scores)), 2), "count": len(scores)}
            for key, scores in sorted(values.items(), key=lambda pair: sum(pair[1]) / max(1, len(pair[1])), reverse=True)
        ]

    return {
        "status": "ready",
        "posted_count": len(records),
        "best_record": best,
        "best_platforms": rank(platform_scores),
        "best_content_pillars": rank(pillar_scores),
        "best_campaign_roles": rank(role_scores),
        "winning_hooks": [item.get("hook") for item in sorted_records[:5] if item.get("hook")],
        "winning_ctas": [item.get("CTA") for item in sorted_records[:5] if item.get("CTA")],
        "average_actual_score": round(sum(_float(item.get("overall_actual_score")) for item in records) / len(records), 2),
        "average_delta": round(sum(_float(item.get("expected_vs_actual_delta")) for item in records) / len(records), 2),
    }


def build_learning_loop(summary: dict[str, Any], feedback: list[dict[str, Any]]) -> dict[str, Any]:
    best_platforms = safe_list(summary.get("best_platforms"))
    best_pillars = safe_list(summary.get("best_content_pillars"))
    best_roles = safe_list(summary.get("best_campaign_roles"))
    top_platform = best_platforms[0].get("name") if best_platforms else "manual upload platforms"
    top_pillar = best_pillars[0].get("name") if best_pillars else "proof"
    top_role = best_roles[0].get("name") if best_roles else "awareness"
    weak_platforms = [item for item in best_platforms if _float(item.get("average_score")) < 55]
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "status": summary.get("status", "needs_input"),
        "winning_audience_segments": sorted({item.get("audience") for item in feedback if item.get("audience")}),
        "winning_hooks": safe_list(summary.get("winning_hooks")),
        "winning_ctas": safe_list(summary.get("winning_ctas")),
        "winning_content_pillars": best_pillars,
        "strong_platforms": best_platforms[:3],
        "weak_platforms": weak_platforms,
        "best_campaign_role": top_role,
        "strongest_campaign_role": top_role,
        "next_5_experiments": [
            f"Post another {top_pillar} clip on {top_platform} with the strongest hook first.",
            "Test the same clip with a shorter caption and direct save CTA.",
            "Pair a proof clip with a behind-the-scenes follow-up.",
            "Repost the best hook angle on a second manual-upload platform.",
            "Use one underperforming clip as a revised-hook test.",
        ],
        "post_less_of": [item.get("platform") for item in feedback if _float(item.get("expected_vs_actual_delta")) < -15][:5],
        "double_down_on": [top_platform, top_pillar, top_role],
    }


def build_next_iteration(summary: dict[str, Any], learning: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "status": summary.get("status", "needs_input"),
        "next_action": "Record post results after manual upload." if summary.get("status") != "ready" else "Build the next seven posts from winning hooks and CTAs.",
        "recommended_adjustments": safe_list(learning.get("next_5_experiments")),
        "what_to_post_next": safe_list(learning.get("double_down_on")),
        "what_to_post_less_of": safe_list(learning.get("post_less_of")),
    }


def write_feedback_markdown(root: Path, summary: dict[str, Any], feedback: list[dict[str, Any]], learning: dict[str, Any], iteration: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    top = feedback[:8]
    write_text(out / "performance_feedback.md", "\n".join([
        "# Performance Feedback",
        "",
        "Manual results only. No live platform APIs are configured.",
        "",
        f"Posted records: {summary.get('posted_count', 0)}",
        f"Average actual score: {summary.get('average_actual_score', 0)}",
        f"Average expected vs actual delta: {summary.get('average_delta', 0)}",
        "",
        "## Posted Clips",
        *[
            f"- {item.get('clip_id')} on {item.get('platform')}: actual {item.get('overall_actual_score')} vs predicted {item.get('predicted_score')} ({item.get('expected_vs_actual_delta')})"
            for item in top
        ],
    ]))
    write_text(out / "next_iteration_plan.md", "\n".join([
        "# Next Iteration Plan",
        "",
        f"Next action: {iteration.get('next_action')}",
        "",
        "## Next Experiments",
        *[f"- {item}" for item in safe_list(learning.get("next_5_experiments"))],
        "",
        "## Double Down On",
        *[f"- {item}" for item in safe_list(learning.get("double_down_on"))],
        "",
        "Manual upload reminder: record results locally after posting.",
    ]))
    return {
        "performance_feedback": relative_path(out / "performance_feedback.md", root),
        "next_iteration_plan": relative_path(out / "next_iteration_plan.md", root),
    }


def build_performance_feedback(root: Path) -> dict[str, Any]:
    project_root = root.resolve()
    recommendations = load_recommendations(project_root)
    cards = load_campaign_cards(project_root)
    history = load_performance_history(project_root)
    context = load_performance_context(project_root)
    feedback = []
    for record in history["records"]:
        clip_id = str(record.get("clip_id") or "")
        platform = str(record.get("platform") or "").lower()
        rec = recommendations.get(clip_id, {})
        card = cards.get(_key(platform, clip_id), cards.get(clip_id, {}))
        feedback.append(score_record(record, rec, card))
    summary = summarize_feedback(feedback)
    learning = build_learning_loop(summary, feedback)
    iteration = build_next_iteration(summary, learning)
    analytics = project_root / "analytics"
    outputs = {
        "performance_feedback": analytics / "performance_feedback.json",
        "campaign_performance_summary": analytics / "campaign_performance_summary.json",
        "marketing_learning_loop": analytics / "marketing_learning_loop.json",
        "next_iteration_plan": analytics / "next_iteration_plan.json",
    }
    write_json(outputs["performance_feedback"], {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "inputs": {
            "manual_post_status": relative_path(project_root / "analytics" / "manual_post_status.json", project_root),
            "marketing_recommendations": relative_path(project_root / "analytics" / "marketing_recommendations.json", project_root),
            "campaign_board": relative_path(project_root / "analytics" / "campaign_board.json", project_root),
            "posting_schedule": relative_path(project_root / "analytics" / "posting_schedule.json", project_root),
            "performance_history": relative_path(project_root / "analytics" / "performance_history.json", project_root),
            "instagram_performance_summary": relative_path(project_root / "analytics" / "instagram_performance_summary.json", project_root),
            "approved_reviews": relative_path(project_root / "queue" / "approved_reviews.json", project_root),
            "social_export_manifest": relative_path(project_root / "out" / "social_exports" / "manifest.json", project_root),
        },
        "input_counts": {
            "manual_post_status": len(_payload_items(context["manual_post_status"], ("records", "items", "statuses"))),
            "posting_schedule": len(_payload_items(context["posting_schedule"], ("seven_day_schedule", "items", "next_7_posts"))),
            "approved_reviews": len(_payload_items(context["approved_reviews"], ("entries", "approved", "approved_clip_ids"))),
            "social_export_manifest": len(_payload_items(context["social_export_manifest"], ("exports", "items", "platforms"))),
            "performance_history": len(history["manual_records"]),
            "imported_summary_records": len(history["imported_summary_records"]),
            "marketing_recommendations": len(recommendations),
            "campaign_cards": len(cards),
        },
        "records": feedback,
        "summary": summary,
    })
    write_json(outputs["campaign_performance_summary"], summary)
    write_json(outputs["marketing_learning_loop"], learning)
    write_json(outputs["next_iteration_plan"], iteration)
    markdown_outputs = write_feedback_markdown(project_root, summary, feedback, learning, iteration)
    return {
        "ok": True,
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "records": len(feedback),
        "status": summary.get("status"),
        "analytics_outputs": {key: relative_path(path, project_root) for key, path in outputs.items()},
        "markdown_outputs": markdown_outputs,
    }


def record_post_result(root: Path, values: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    clip_id = str(values.get("clip_id") or "").strip()
    platform = str(values.get("platform") or "").strip().lower()
    if not clip_id:
        raise ValueError("--clip-id is required")
    if not platform:
        raise ValueError("--platform is required")
    retention_percent = normalize_retention_percent(values.get("retention_percent", values.get("retention")))
    record = {
        "record_id": f"perf_{platform}_{clip_id}",
        "record_source": "manual",
        "clip_id": clip_id,
        "platform": platform,
        "posted_at": values.get("posted_at") or utc_now(),
        "views": _float(values.get("views")),
        "likes": _float(values.get("likes")),
        "comments": _float(values.get("comments")),
        "shares": _float(values.get("shares")),
        "saves": _float(values.get("saves")),
        "watch_time": _float(values.get("watch_time")),
        "retention": retention_percent,
        "retention_percent": retention_percent,
        "profile_visits": _float(values.get("profile_visits")),
        "follows": _float(values.get("follows")),
        "notes": values.get("notes") or "",
        "updated_at": utc_now(),
        "local_only": True,
        "manual_entry": True,
    }
    recommendations = load_recommendations(project_root)
    cards = load_campaign_cards(project_root)
    rec = recommendations.get(clip_id, {})
    card = cards.get(_key(platform, clip_id), cards.get(clip_id, {}))
    scored = score_record(record, rec, card)
    predicted = scored.get("predicted_score") or 0
    actual = scored.get("overall_actual_score") or 0
    record.update({
        "metrics": {
            "views": record["views"],
            "likes": record["likes"],
            "comments": record["comments"],
            "shares": record["shares"],
            "saves": record["saves"],
            "watch_time": record["watch_time"],
            "retention_percent": record["retention_percent"],
            "profile_visits": record["profile_visits"],
            "follows": record["follows"],
        },
        "predicted_hook_score": predicted,
        "actual_performance_score": actual,
        "learning_delta": round(actual - predicted, 2),
        "hook": scored.get("hook") or card.get("hook") or rec.get("hook") or "",
        "scene_labels": safe_list(card.get("scene_labels") or rec.get("scene_labels")),
        "hook_moments": safe_list(card.get("hook_moments") or rec.get("hook_moments")),
        "clip_length_seconds": _float(card.get("duration_seconds") or rec.get("duration_seconds"), 0.0),
        "clip_length_bucket": card.get("clip_length_bucket") or "manual_result",
        "posting_pattern": str(record["posted_at"] or "")[:13].replace("T", "_hour_"),
        "source": "manual_result",
    })
    history = load_manual_performance_history(project_root)
    records = [item for item in history["records"] if item.get("record_id") != record["record_id"]]
    records.append(record)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "records": records,
    }
    if not dry_run:
        write_json(project_root / "analytics" / "performance_history.json", payload)
        feedback = build_performance_feedback(project_root)
    else:
        feedback = {"ok": True, "dry_run": True}
    return {
        "ok": True,
        "dry_run": dry_run,
        "local_only": True,
        "manual_entry_only": True,
        "direct_posting_apis": False,
        "record": record,
        "history_count": len(records),
        "feedback": feedback,
    }
