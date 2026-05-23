from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import AppConfig
from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
PLATFORMS = {
    "tiktok": {"aspect_ratio": "9:16", "max_seconds": 180},
    "instagram_reels": {"aspect_ratio": "9:16", "max_seconds": 90},
    "youtube_shorts": {"aspect_ratio": "9:16", "max_seconds": 60},
    "facebook_reels": {"aspect_ratio": "9:16", "max_seconds": 90},
}


def _analytics(config: AppConfig, name: str) -> Path:
    return config.analytics_dir / name


def _outputs(config: AppConfig) -> dict[str, Path]:
    base = config.root / "out" / "post_editor"
    paths = {
        "base": base,
        "previews": base / "previews",
        "renders": base / "renders",
        "thumbnails": base / "thumbnails",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _load_queue(config: AppConfig) -> list[dict[str, Any]]:
    payload = load_json_file(config.queue_dir / "review_queue.json", {"entries": []})
    entries = payload.get("entries") or payload.get("items") or payload.get("queue") or []
    return entries if isinstance(entries, list) else []


def _resolve_source(config: AppConfig, value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value).expanduser()
    path = raw if raw.is_absolute() else config.root / raw
    try:
        return path.resolve()
    except OSError:
        return path


def _source_for_entry(config: AppConfig, entry: dict[str, Any]) -> Path | None:
    for key in ("clip_path", "video_path", "image_path", "source_path", "path", "media_path"):
        source = _resolve_source(config, entry.get(key))
        if source and source.exists():
            return source
    return None


def _source_for_request(
    config: AppConfig,
    *,
    clip_id: str | None = None,
    image: str | None = None,
    video: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    explicit = _resolve_source(config, image or video)
    if explicit:
        return explicit, {"clip_id": clip_id or explicit.stem, "title": explicit.name}
    entries = _load_queue(config)
    if clip_id:
        for entry in entries:
            if str(entry.get("clip_id") or entry.get("id") or "") == str(clip_id):
                return _source_for_entry(config, entry), entry
    for entry in entries:
        source = _source_for_entry(config, entry)
        if source:
            return source, entry
    return None, {}


def detect_media_type(path: Path | None) -> str:
    if not path:
        return "unknown"
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "unknown"


def _plan_id(source: Path | None, platform: str, notes: str, clip_id: str | None) -> str:
    basis = "|".join([str(source or ""), platform, notes, clip_id or "", utc_now()])
    return "edit_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _read_plans(config: AppConfig) -> list[dict[str, Any]]:
    payload = load_json_file(_analytics(config, "edit_plans.json"), {"plans": []})
    plans = payload.get("plans", [])
    return plans if isinstance(plans, list) else []


def _write_plans(config: AppConfig, plans: list[dict[str, Any]]) -> None:
    save_json_file(_analytics(config, "edit_plans.json"), {"updated_at": utc_now(), "plans": plans})


def _read_jobs(config: AppConfig) -> list[dict[str, Any]]:
    payload = load_json_file(_analytics(config, "edit_jobs.json"), {"jobs": []})
    jobs = payload.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _write_jobs(config: AppConfig, jobs: list[dict[str, Any]]) -> None:
    save_json_file(_analytics(config, "edit_jobs.json"), {"updated_at": utc_now(), "jobs": jobs})


def editing_capabilities(config: AppConfig) -> dict[str, Any]:
    outputs = _outputs(config)
    payload = {
        "status": "ready",
        "updated_at": utc_now(),
        "local_only": True,
        "cloud_editing_api_enabled": False,
        "non_destructive": True,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "supported_image_extensions": sorted(IMAGE_EXTENSIONS),
        "supported_video_extensions": sorted(VIDEO_EXTENSIONS),
        "output_paths": {key: relative_path(path, config.root) for key, path in outputs.items() if key != "base"},
    }
    save_json_file(_analytics(config, "editing_capabilities.json"), payload)
    return payload


def build_edit_plan(
    config: AppConfig,
    *,
    clip_id: str | None = None,
    image: str | None = None,
    video: str | None = None,
    platform: str = "tiktok",
    notes: str = "",
    dry_run: bool = True,
) -> dict[str, Any]:
    outputs = _outputs(config)
    source, entry = _source_for_request(config, clip_id=clip_id, image=image, video=video)
    media_type = detect_media_type(source)
    platform = platform if platform in PLATFORMS else "tiktok"
    plan_id = _plan_id(source, platform, notes, entry.get("clip_id") or clip_id)
    source_exists = bool(source and source.exists())
    preview_ext = ".png" if media_type == "image" else ".mp4"
    plan = {
        "plan_id": plan_id,
        "clip_id": entry.get("clip_id") or clip_id or (source.stem if source else None),
        "title": entry.get("title") or entry.get("clip_id") or (source.name if source else "Untitled asset"),
        "source_path": relative_path(source, config.root) if source else None,
        "source_exists": source_exists,
        "source_sha1": None,
        "media_type": media_type,
        "platform": platform,
        "platform_spec": PLATFORMS[platform],
        "user_edit_notes": notes,
        "status": "planned" if source_exists else "source_required",
        "dry_run": dry_run,
        "non_destructive": True,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "operations": [
            {"operation": "crop", "target": "9:16 safe frame", "destructive": False},
            {"operation": "trim", "target": "strongest hook and end beat", "destructive": False},
            {"operation": "caption_overlay", "target": "readable social captions", "destructive": False},
            {"operation": "title_card", "target": "optional first-frame hook", "destructive": False},
            {"operation": "cta_end_card", "target": "manual upload CTA", "destructive": False},
            {"operation": "color_boost", "target": "subtle contrast and saturation lift", "destructive": False},
            {"operation": "audio_normalize", "target": "local loudness pass for video", "destructive": False},
            {"operation": "thumbnail_frame", "target": "high-contrast preview frame", "destructive": False},
            {"operation": "platform_version", "target": platform, "destructive": False},
        ],
        "preview_path": relative_path(outputs["previews"] / f"{plan_id}_preview{preview_ext}", config.root),
        "render_path": relative_path(outputs["renders"] / f"{plan_id}_{platform}{preview_ext}", config.root),
        "thumbnail_path": relative_path(outputs["thumbnails"] / f"{plan_id}_thumb.png", config.root),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    plans = _read_plans(config)
    plans.append(plan)
    _write_plans(config, plans)
    caps = editing_capabilities(config)
    client_state = {
        "status": plan["status"],
        "updated_at": utc_now(),
        "active_plan": plan,
        "capabilities": {
            "ffmpeg_available": caps["ffmpeg_available"],
            "non_destructive": True,
            "original_media_protected": True,
            "cloud_editing_api_enabled": False,
        },
    }
    save_json_file(_analytics(config, "client_editing_state.json"), client_state)
    return {"status": "pass" if source_exists or dry_run else "warn", "plan": plan, "capabilities": caps}


def _find_plan(config: AppConfig, plan_id: str | None, clip_id: str | None) -> dict[str, Any] | None:
    plans = _read_plans(config)
    if plan_id:
        for plan in plans:
            if str(plan.get("plan_id")) == str(plan_id):
                return plan
    if clip_id:
        for plan in reversed(plans):
            if str(plan.get("clip_id")) == str(clip_id):
                return plan
    return plans[-1] if plans else None


def _safe_output(config: AppConfig, rel_value: str | None, folder: Path, fallback_name: str, source: Path | None = None) -> Path:
    path = config.root / rel_value if rel_value else folder / fallback_name
    resolved = path.resolve()
    folder_root = folder.resolve()
    try:
        resolved.relative_to(folder_root)
    except ValueError as error:
        raise ValueError("Render output must stay inside out/post_editor.")
    if source and source.resolve() == resolved:
        raise ValueError("Render output cannot equal source media.")
    if resolved.exists():
        stem = resolved.stem
        suffix = resolved.suffix
        resolved = resolved.with_name(f"{stem}_{hashlib.sha1(utc_now().encode()).hexdigest()[:6]}{suffix}")
    return resolved


def create_preview_job(config: AppConfig, *, plan_id: str | None = None, clip_id: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    outputs = _outputs(config)
    plan = _find_plan(config, plan_id, clip_id)
    if not plan:
        job = {
            "job_id": "preview_" + hashlib.sha1(f"missing|{utc_now()}".encode()).hexdigest()[:10],
            "type": "preview",
            "plan_id": plan_id,
            "clip_id": clip_id,
            "dry_run": dry_run,
            "status": "edit_plan_required",
            "client_message": "Build a non-destructive edit plan before rendering a preview.",
            "original_media_protected": True,
            "source_overwrite_allowed": False,
            "created_at": utc_now(),
        }
        jobs = _read_jobs(config)
        jobs.append(job)
        _write_jobs(config, jobs)
        save_json_file(_analytics(config, "client_editing_state.json"), {"status": "edit_plan_required", "updated_at": utc_now(), "last_job": job})
        return {"status": "warn", "job": job}
    source = _resolve_source(config, plan.get("source_path"))
    out_path = _safe_output(config, plan.get("preview_path"), outputs["previews"], f"{plan['plan_id']}_preview.mp4", source)
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    status = "preview_ready_dry_run" if dry_run else "ffmpeg_required"
    if not dry_run and ffmpeg_ok and source and source.exists():
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-t", "3", str(out_path)]
        result = subprocess.run(command, cwd=config.root, capture_output=True, text=True, check=False)
        status = "rendered" if result.returncode == 0 else "failed"
    job = {
        "job_id": "preview_" + hashlib.sha1(f"{plan['plan_id']}|{utc_now()}".encode()).hexdigest()[:10],
        "type": "preview",
        "plan_id": plan["plan_id"],
        "clip_id": plan.get("clip_id"),
        "source_path": plan.get("source_path"),
        "output_path": relative_path(out_path, config.root),
        "dry_run": dry_run,
        "ffmpeg_available": ffmpeg_ok,
        "status": status,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "created_at": utc_now(),
    }
    jobs = _read_jobs(config)
    jobs.append(job)
    _write_jobs(config, jobs)
    save_json_file(_analytics(config, "client_editing_state.json"), {"status": status, "updated_at": utc_now(), "active_plan": plan, "last_job": job})
    return {"status": "pass" if dry_run or status == "rendered" else "warn", "job": job}


def create_final_render_job(config: AppConfig, *, plan_id: str | None = None, approve: bool = False, dry_run: bool = True) -> dict[str, Any]:
    outputs = _outputs(config)
    plan = _find_plan(config, plan_id, None)
    if not plan:
        job = {
            "job_id": "final_" + hashlib.sha1(f"missing|{utc_now()}".encode()).hexdigest()[:10],
            "type": "final_render",
            "plan_id": plan_id,
            "dry_run": dry_run,
            "approved": approve,
            "status": "edit_plan_required",
            "client_message": "Build and review an edit plan before approving a final render.",
            "final_render_requires_approval": True,
            "original_media_protected": True,
            "source_overwrite_allowed": False,
            "delete_source_allowed": False,
            "created_at": utc_now(),
        }
        jobs = _read_jobs(config)
        jobs.append(job)
        _write_jobs(config, jobs)
        save_json_file(_analytics(config, "client_editing_state.json"), {"status": "edit_plan_required", "updated_at": utc_now(), "last_job": job})
        return {"status": "warn", "job": job}
    source = _resolve_source(config, plan.get("source_path"))
    out_path = _safe_output(config, plan.get("render_path"), outputs["renders"], f"{plan['plan_id']}_final.mp4", source)
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    status = "final_render_dry_run" if dry_run else "approval_required"
    if not dry_run and approve and ffmpeg_ok:
        if source and source.exists():
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), str(out_path)]
            result = subprocess.run(command, cwd=config.root, capture_output=True, text=True, check=False)
            status = "rendered" if result.returncode == 0 else "failed"
        else:
            status = "missing_source"
    elif not dry_run and not approve:
        status = "approval_required"
    job = {
        "job_id": "final_" + hashlib.sha1(f"{plan['plan_id']}|{utc_now()}".encode()).hexdigest()[:10],
        "type": "final_render",
        "plan_id": plan["plan_id"],
        "clip_id": plan.get("clip_id"),
        "output_path": relative_path(out_path, config.root),
        "dry_run": dry_run,
        "approved": approve,
        "ffmpeg_available": ffmpeg_ok,
        "status": status,
        "final_render_requires_approval": True,
        "original_media_protected": True,
        "source_overwrite_allowed": False,
        "delete_source_allowed": False,
        "created_at": utc_now(),
    }
    jobs = _read_jobs(config)
    jobs.append(job)
    _write_jobs(config, jobs)
    manifest = {"updated_at": utc_now(), "renders": [job], "manual_upload_fallback": True}
    save_json_file(outputs["renders"] / "manifest.json", manifest)
    save_json_file(_analytics(config, "client_editing_state.json"), {"status": status, "updated_at": utc_now(), "active_plan": plan, "last_job": job})
    return {"status": "pass" if dry_run or status == "rendered" else "warn", "job": job}
