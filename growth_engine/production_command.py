from __future__ import annotations

from collections import Counter
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


def _load_inputs(root: Path) -> dict[str, Any]:
    analytics = root / "analytics"
    return {
        "client_state": load_json(analytics / "client_state.json", {}),
        "client_workflow": load_json(analytics / "client_workflow.json", {}),
        "client_tasks": load_json(analytics / "client_tasks.json", {}),
        "marketing_recommendations": load_json(analytics / "marketing_recommendations.json", {}),
        "campaign_board": load_json(analytics / "campaign_board.json", {}),
        "posting_schedule": load_json(analytics / "posting_schedule.json", {}),
        "client_campaign_plan": load_json(analytics / "client_campaign_plan.json", {}),
        "growth_dashboard": load_json(analytics / "growth_dashboard.json", {}),
        "next_best_actions": load_json(analytics / "next_best_actions.json", {}),
        "creative_director_brief": load_json(analytics / "creative_director_brief.json", {}),
        "client_creative_plan": load_json(analytics / "client_creative_plan.json", {}),
        "hook_bank": load_json(analytics / "hook_bank.json", {}),
        "caption_variations": load_json(analytics / "caption_variations.json", {}),
        "script_ideas": load_json(analytics / "script_ideas.json", {}),
        "ab_test_plan": load_json(analytics / "ab_test_plan.json", {}),
        "performance_feedback": load_json(analytics / "performance_feedback.json", {}),
        "manual_post_status": load_json(analytics / "manual_post_status.json", {}),
        "review_queue": load_json(root / "queue" / "review_queue.json", {}),
        "approved_reviews": load_json(root / "queue" / "approved_reviews.json", {}),
        "social_manifest": load_json(root / "out" / "social_exports" / "manifest.json", {}),
    }


def _queue_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("review_queue") or {}
    for key in ("items", "queue", "clips", "entries"):
        items = safe_list(payload.get(key))
        if items:
            return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


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
    for item in _queue_items(data):
        status = str(item.get("status") or item.get("review_status") or "").lower()
        if status == "approved":
            clip_id = item.get("clip_id") or item.get("id") or item.get("entry_id")
            if clip_id:
                approved.add(str(clip_id))
    return approved


def _clip_id(item: dict[str, Any]) -> str:
    return str(item.get("clip_id") or item.get("id") or item.get("entry_id") or item.get("queue_id") or "")


def _clip_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("caption") or item.get("clip_id") or item.get("id") or "Clip")


def _recommendations(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["marketing_recommendations"].get("recommendations")) if isinstance(item, dict)]


def _campaign_cards(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["campaign_board"].get("cards")) if isinstance(item, dict)]


def _next_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["next_best_actions"].get("actions")) if isinstance(item, dict)]


def _creative_assets(data: dict[str, Any]) -> dict[str, int]:
    return {
        "hooks": len(safe_list(data["hook_bank"].get("hooks"))),
        "captions": len(safe_list(data["caption_variations"].get("captions"))),
        "scripts": len(safe_list(data["script_ideas"].get("ideas"))),
        "tests": len(safe_list(data["ab_test_plan"].get("tests"))),
    }


def _social_exports(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["social_manifest"].get("exports")) if isinstance(item, dict)]


def _manual_status_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("manual_post_status") or {}
    for key in ("records", "statuses", "items"):
        items = safe_list(payload.get(key))
        if items:
            return [item for item in items if isinstance(item, dict)]
    return []


def _performance_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in safe_list(data["performance_feedback"].get("records")) if isinstance(item, dict)]


def _action(action_id: str, title: str, category: str, priority: int, effort: str, impact: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "title": title,
        "category": category,
        "priority": priority,
        "effort": effort,
        "expected_impact": impact,
        "due_label": extra.pop("due_label", "Today"),
        "client_message": message,
        "status": extra.pop("status", "open"),
        **extra,
    }


def build_today_action_plan(data: dict[str, Any], today: str | None = None) -> dict[str, Any]:
    items = _queue_items(data)
    approved = _approved_ids(data)
    exports = _social_exports(data)
    exported_ids = {str(item.get("clip_id")) for item in exports if item.get("clip_id")}
    pending = [item for item in items if str(item.get("status") or item.get("review_status") or "pending").lower() in {"pending", "needs_review", "review"}]
    high_score = sorted(items, key=lambda item: _num(item.get("score")), reverse=True)
    clips_to_review = high_score[:5]
    clips_to_approve = [item for item in high_score if _clip_id(item) not in approved][:5]
    packs_to_export = [clip_id for clip_id in approved if clip_id not in exported_ids]
    manual_records = _manual_status_records(data)
    uploaded = {str(item.get("clip_id")) for item in manual_records if str(item.get("status")) == "uploaded_manually"}
    posts_to_upload = [item for item in exports if str(item.get("clip_id")) not in uploaded]
    creative_assets = _creative_assets(data)
    next_growth = _next_actions(data)
    campaign_cards = _campaign_cards(data)
    feedback = _performance_records(data)
    actions: list[dict[str, Any]] = []

    if pending:
        actions.append(_action("review_ready_clips", f"Review {min(len(pending), 5)} ready clips.", "review", 96, "low", "Move the best clips into approval and export.", "Review the strongest clips and approve the winners.", linked_clip_id=_clip_id(pending[0])))
    if clips_to_approve:
        actions.append(_action("approve_best_clip", "Approve the best clip for the next post.", "approve", 92, "low", "Unlocks export and manual upload.", "Approve the strongest clip so HigherKey can prepare the social packs.", linked_clip_id=_clip_id(clips_to_approve[0])))
    if packs_to_export:
        actions.append(_action("export_approved_packs", "Export packs for approved clips.", "export", 90, "low", "Creates ready-to-upload platform folders.", "Export local packs for manual upload.", linked_clip_id=packs_to_export[0]))
    if posts_to_upload:
        first = posts_to_upload[0]
        actions.append(_action("upload_next_pack", "Upload the next prepared social pack manually.", "upload", 88, "medium", "Starts the learning loop with real results.", "Open the export folder and upload the prepared files manually.", linked_clip_id=first.get("clip_id"), linked_platform=first.get("platform") or first.get("platform_key"), folder_path=first.get("folder") or first.get("output_dir")))
    if not feedback and (uploaded or posts_to_upload or exports):
        actions.append(_action("record_manual_results", "Record results after manual upload.", "record_results", 84, "low", "Improves future recommendations.", "Enter views, saves, shares, and follows after posting.", linked_platform=(posts_to_upload[0].get("platform") if posts_to_upload else None)))
    if min(creative_assets.values() or [0]) == 0:
        actions.append(_action("build_creative_direction", "Build creative direction for the next post.", "create", 80, "low", "Creates hooks, captions, thumbnails, scripts, and A/B tests.", "Generate Creative Director assets before the next manual upload."))
    if next_growth:
        top = next_growth[0]
        actions.append(_action("execute_growth_action", str(top.get("title") or "Execute the top growth action."), "create", int(_num(top.get("priority"), 70)), str(top.get("effort") or "medium"), str(top.get("expected_impact") or "Clearer growth focus."), str(top.get("why_it_matters") or "This is the top growth recommendation."), linked_clip_id=top.get("linked_clip_id"), linked_platform=top.get("linked_platform"), linked_campaign=top.get("linked_campaign")))
    if not items:
        actions.append(_action("import_footage", "Import footage to begin.", "import", 98, "low", "Gives HigherKey material to process.", "Drop MP4, MOV, or M4V footage into the app."))
    if data["client_tasks"].get("running_count"):
        actions.append(_action("wait_for_processing", "Let processing finish.", "process", 86, "low", "Keeps generated clips consistent.", "HigherKey is processing local media now.", status="processing"))

    actions = sorted(actions, key=lambda item: item["priority"], reverse=True)
    return {
        "version": 1,
        "updated_at": utc_now(),
        "date": today or utc_now()[:10],
        "local_only": True,
        "manual_upload_only": True,
        "top_priority": actions[0] if actions else None,
        "next_3_actions": actions[:3],
        "actions": actions,
        "clips_to_review": [_card_from_clip(item, "Ready for Review", "Review this clip.") for item in clips_to_review],
        "clips_to_approve": [_card_from_clip(item, "Ready to Approve", "Approve if it fits the campaign.") for item in clips_to_approve],
        "packs_to_export": packs_to_export,
        "posts_to_upload_manually": posts_to_upload[:8],
        "creative_assets_to_prepare": creative_assets,
        "results_to_record": [item for item in manual_records if item.get("status") == "uploaded_manually"] or posts_to_upload[:5],
        "campaign_items_needing_attention": [item for item in campaign_cards if str(item.get("status", "")).lower() in {"needs_revision", "needs_attention"}][:5],
        "recommended_shoots_or_imports": [item for item in safe_list(data["script_ideas"].get("ideas"))[:5]],
    }


def _card_from_clip(item: dict[str, Any], status: str, next_action: str) -> dict[str, Any]:
    clip_id = _clip_id(item)
    return {
        "card_id": f"clip_{clip_id}" if clip_id else f"clip_{abs(hash(str(item))) % 99999}",
        "title": _clip_title(item),
        "clip_id": clip_id or None,
        "platform": item.get("platform"),
        "campaign": item.get("campaign_role") or item.get("campaign"),
        "score": _num(item.get("score")),
        "status": status,
        "blocker": None,
        "next_action": next_action,
        "folder_path": item.get("package_path") or item.get("clip_path"),
        "priority": int(_num(item.get("score"), 50)),
    }


def build_content_readiness_board(data: dict[str, Any]) -> dict[str, Any]:
    items = _queue_items(data)
    approved = _approved_ids(data)
    exports = _social_exports(data)
    exported_ids = {str(item.get("clip_id")) for item in exports if item.get("clip_id")}
    manual_records = _manual_status_records(data)
    uploaded = {str(item.get("clip_id")) for item in manual_records if str(item.get("status")) == "uploaded_manually"}
    recs = _recommendations(data)
    columns: dict[str, list[dict[str, Any]]] = {
        "Needs Footage": [],
        "Needs Processing": [],
        "Ready for Review": [],
        "Ready to Approve": [],
        "Ready for Export": [],
        "Ready for Upload": [],
        "Posted / Waiting Results": [],
        "Needs Creative Work": [],
        "Needs Attention": [],
    }
    if not items:
        columns["Needs Footage"].append({"card_id": "needs_footage", "title": "Import footage to begin", "status": "Needs Footage", "blocker": "No clips available", "next_action": "Import Footage", "priority": 95})
    for item in sorted(items, key=lambda clip: _num(clip.get("score")), reverse=True)[:40]:
        clip_id = _clip_id(item)
        status = str(item.get("status") or item.get("review_status") or "pending").lower()
        if status in {"rejected", "archived"}:
            continue
        if clip_id in uploaded:
            column, label, action = "Posted / Waiting Results", "Posted / Waiting Results", "Record results"
        elif clip_id in exported_ids:
            column, label, action = "Ready for Upload", "Ready for Upload", "Upload manually"
        elif clip_id in approved:
            column, label, action = "Ready for Export", "Ready for Export", "Export social packs"
        elif status == "approved":
            column, label, action = "Ready for Export", "Ready for Export", "Export social packs"
        else:
            column, label, action = "Ready for Review", "Ready for Review", "Review and approve"
        columns[column].append(_card_from_clip(item, label, action))
    for rec in recs[:8]:
        if not rec.get("recommended_caption_style") or not rec.get("recommended_CTA") and not rec.get("recommended_cta"):
            columns["Needs Creative Work"].append({
                "card_id": f"creative_{rec.get('clip_id', len(columns['Needs Creative Work']))}",
                "title": str(rec.get("title") or rec.get("clip_id") or "Creative recommendation"),
                "clip_id": rec.get("clip_id"),
                "platform": rec.get("platform"),
                "campaign": rec.get("campaign_role"),
                "score": _num(rec.get("score") or rec.get("confidence")),
                "status": "Needs Creative Work",
                "blocker": "Creative direction not finalized",
                "next_action": "Build Creative Direction",
                "priority": 72,
            })
    if data["client_state"].get("health_status") not in {None, "healthy", "pass"}:
        columns["Needs Attention"].append({"card_id": "health_attention", "title": "Project needs attention", "status": "Needs Attention", "blocker": data["client_state"].get("pipeline_message") or "Open Support", "next_action": "Open Support", "priority": 88})
    return {"version": 1, "updated_at": utc_now(), "local_only": True, "columns": [{"name": name, "cards": cards} for name, cards in columns.items()]}


def build_operator_priorities(data: dict[str, Any], plan: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
    items = _queue_items(data)
    exports = _social_exports(data)
    next_actions = _next_actions(data)
    creative = data["creative_director_brief"] if isinstance(data["creative_director_brief"], dict) else {}
    scripts = safe_list(data["script_ideas"].get("ideas"))
    platforms = Counter(str(item.get("platform") or item.get("platform_key") or "").lower() for item in exports)
    highest = max(items, key=lambda item: _num(item.get("score")), default={})
    best_post = plan.get("posts_to_upload_manually", [None])[0] if plan.get("posts_to_upload_manually") else None
    bottlenecks = [(col["name"], len(col["cards"])) for col in board.get("columns", [])]
    bottleneck = max(bottlenecks, key=lambda item: item[1], default=("None", 0))[0]
    primary_platform = platforms.most_common(1)[0][0] if platforms else (next_actions[0].get("linked_platform") if next_actions else "tiktok")
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "manual_upload_only": True,
        "highest_value_clip": _card_from_clip(highest, "Highest Value Clip", "Review or export this clip") if highest else None,
        "best_next_post": best_post,
        "best_next_platform": PLATFORM_LABELS.get(primary_platform, primary_platform),
        "best_next_creative_test": (safe_list(data["ab_test_plan"].get("tests")) or [{}])[0],
        "best_next_campaign_move": next_actions[0] if next_actions else plan.get("top_priority"),
        "best_next_shoot_or_import_idea": scripts[0] if scripts else {"title": "Import more footage with a clear opening hook."},
        "biggest_bottleneck": bottleneck,
        "main_warning": "Record manual post results to improve strategy." if not _performance_records(data) else "Keep uploading and recording results.",
        "creative_thesis": creative.get("campaign_creative_thesis") or creative.get("creative_thesis"),
    }


def write_markdown(root: Path, command: dict[str, Any], plan: dict[str, Any], board: dict[str, Any], priorities: dict[str, Any]) -> dict[str, str]:
    out = root / "out" / "marketing"
    out.mkdir(parents=True, exist_ok=True)
    write_text(out / "today_action_plan.md", "\n".join(["# Today's Action Plan", "", *[f"- {item['title']} ({item['category']}) - {item['client_message']}" for item in plan.get("actions", [])], "", "Manual upload only. HigherKey prepares local files; the operator uploads them."]))
    write_text(out / "production_command_center.md", "\n".join(["# Production Command Center", "", f"Status: {command['status']}", f"Top priority: {plan.get('top_priority', {}).get('title', 'None') if plan.get('top_priority') else 'None'}", "", "## Next 3 Actions", *[f"- {item['title']}" for item in plan.get("next_3_actions", [])]]))
    write_text(out / "content_readiness_board.md", "\n".join(["# Content Readiness Board", "", *[f"## {col['name']}\n" + "\n".join(f"- {card['title']} → {card['next_action']}" for card in col.get("cards", [])) for col in board.get("columns", [])]]))
    write_text(out / "operator_priorities.md", "\n".join(["# Operator Priorities", "", f"- Best next platform: {priorities.get('best_next_platform')}", f"- Biggest bottleneck: {priorities.get('biggest_bottleneck')}", f"- Main warning: {priorities.get('main_warning')}"]))
    return {key: relative_path(out / f"{key}.md", root) for key in ("today_action_plan", "production_command_center", "content_readiness_board", "operator_priorities")}


def build_production_command(root: Path, today: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    data = _load_inputs(project_root)
    plan = build_today_action_plan(data, today=today)
    board = build_content_readiness_board(data)
    priorities = build_operator_priorities(data, plan, board)
    ready_upload = len(plan.get("posts_to_upload_manually", []))
    ready_review = len(plan.get("clips_to_review", []))
    status = "Waiting for Footage" if not _queue_items(data) else ("Needs Attention" if priorities.get("main_warning", "").startswith("Record") else "Ready")
    command = {
        "version": 1,
        "updated_at": utc_now(),
        "date": plan["date"],
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "status": status,
        "hero": {
            "title": "Today's Content Command",
            "top_priority": plan.get("top_priority"),
            "next_best_action": plan.get("next_3_actions", [None])[0] if plan.get("next_3_actions") else None,
        },
        "top_cards": {
            "ready_to_review": ready_review,
            "ready_to_export": len(plan.get("packs_to_export", [])),
            "ready_to_upload": ready_upload,
            "needs_creative": len([col for col in board["columns"] if col["name"] == "Needs Creative Work" for _ in col["cards"]]),
            "results_to_record": len(plan.get("results_to_record", [])),
            "best_next_post": priorities.get("best_next_post"),
        },
        "today_action_plan": plan,
        "content_readiness_board": board,
        "operator_priorities": priorities,
    }
    client_daily = {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "local_only": True,
        "manual_upload_only": True,
        "message": plan.get("top_priority", {}).get("client_message") if plan.get("top_priority") else "Import footage to begin.",
        "top_priority": plan.get("top_priority"),
        "next_3_actions": plan.get("next_3_actions", []),
        "ready_to_upload": ready_upload,
        "ready_to_review": ready_review,
    }
    markdown = {} if dry_run else write_markdown(project_root, command, plan, board, priorities)
    if not dry_run:
        analytics = project_root / "analytics"
        write_json(analytics / "production_command_center.json", command)
        write_json(analytics / "today_action_plan.json", plan)
        write_json(analytics / "content_readiness_board.json", board)
        write_json(analytics / "operator_priorities.json", priorities)
        write_json(analytics / "client_daily_plan.json", client_daily)
    return {
        "ok": True,
        "dry_run": dry_run,
        "local_only": True,
        "manual_upload_only": True,
        "direct_posting_apis": False,
        "live_instagram_api": False,
        "status": status,
        "actions": len(plan.get("actions", [])),
        "ready_to_upload": ready_upload,
        "markdown_outputs": markdown,
    }
