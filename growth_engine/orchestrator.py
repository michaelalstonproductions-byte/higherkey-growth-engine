from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .analytics import build_learning_outputs, load_json, save_json
from .config import AppConfig, ensure_directories
from .exporter import export_approved_posts
from .index import utc_now
from .ingest import discover_videos
from .jobs import enqueue_new_videos, process_next_job
from .local_ai import build_metadata_index
from .pipeline import process_once


AGENT_STATES = {"idle", "assigned", "running", "completed", "failed", "disabled"}


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    role: str
    capabilities: tuple[str, ...]


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("ingest", "Ingest Agent", "Find local media and queue it for processing.", ("discover_videos", "enqueue_jobs")),
    AgentSpec("clip_generation", "Clip Generation Agent", "Run the existing local clip pipeline.", ("process_once", "generate_clips")),
    AgentSpec("content_intelligence", "Content Intelligence Agent", "Validate local clip analysis outputs.", ("score_clips", "inspect_analysis")),
    AgentSpec("metadata_indexing", "Metadata Indexing Agent", "Build the local searchable metadata index.", ("build_metadata_index",)),
    AgentSpec("analytics_learning", "Analytics Learning Agent", "Refresh local learning summaries from performance history.", ("build_learning_outputs",)),
    AgentSpec("recommendation", "Recommendation Agent", "Rank queue entries with deterministic local signals.", ("rank_queue",)),
    AgentSpec("export", "Export Agent", "Export locally approved posts when approvals are present.", ("export_approved_posts",)),
)


def orchestration_paths(config: AppConfig) -> dict[str, Path]:
    return {
        "agents": config.analytics_dir / "agents.json",
        "activity": config.analytics_dir / "agent_activity.json",
        "graph": config.analytics_dir / "orchestration_graph.json",
        "recommendations": config.analytics_dir / "recommendations.json",
    }


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _base_agent(spec: AgentSpec, state: str = "idle") -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "role": spec.role,
        "state": state,
        "enabled": True,
        "assigned_task": None,
        "capabilities": list(spec.capabilities),
        "last_started_at": None,
        "last_completed_at": None,
        "last_error": None,
        "last_summary": None,
    }


def _load_agents(config: AppConfig) -> dict[str, Any]:
    payload = _read(orchestration_paths(config)["agents"], {"version": 1, "agents": []})
    existing = {agent.get("id"): agent for agent in payload.get("agents", [])}
    agents = []
    for spec in AGENTS:
        merged = _base_agent(spec)
        merged.update({key: value for key, value in existing.get(spec.id, {}).items() if key in merged})
        if merged["state"] not in AGENT_STATES:
            merged["state"] = "idle"
        agents.append(merged)
    return {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "execution_mode": "sequential",
        "states": sorted(AGENT_STATES),
        "agents": agents,
    }


def _write_agents(config: AppConfig, payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now()
    save_json(orchestration_paths(config)["agents"], payload)


def _append_activity(config: AppConfig, agent_id: str, event: str, message: str, summary: dict[str, Any] | None = None) -> None:
    path = orchestration_paths(config)["activity"]
    payload = _read(path, {"version": 1, "local_only": True, "events": []})
    payload.setdefault("events", []).append(
        {
            "at": utc_now(),
            "agent_id": agent_id,
            "event": event,
            "message": message,
            "summary": summary or {},
        }
    )
    payload["events"] = payload["events"][-300:]
    payload["updated_at"] = utc_now()
    save_json(path, payload)


def write_orchestration_graph(config: AppConfig) -> dict[str, Any]:
    nodes = [
        {"id": spec.id, "label": spec.name, "role": spec.role}
        for spec in AGENTS
    ]
    order = [spec.id for spec in AGENTS]
    edges = [
        {"from": order[index], "to": order[index + 1], "type": "sequential_placeholder"}
        for index in range(len(order) - 1)
    ]
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "execution_mode": "sequential",
        "parallel_execution": {"status": "placeholder", "enabled": False},
        "nodes": nodes,
        "edges": edges,
    }
    save_json(orchestration_paths(config)["graph"], payload)
    return payload


def _agent_record(payload: dict[str, Any], agent_id: str) -> dict[str, Any]:
    return next(agent for agent in payload["agents"] if agent["id"] == agent_id)


def _set_state(
    config: AppConfig,
    payload: dict[str, Any],
    agent_id: str,
    state: str,
    assigned_task: str | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    agent = _agent_record(payload, agent_id)
    agent["state"] = state
    agent["assigned_task"] = assigned_task
    if state == "running":
        agent["last_started_at"] = utc_now()
    if state in {"completed", "failed"}:
        agent["last_completed_at"] = utc_now()
        agent["assigned_task"] = None
    if summary is not None:
        agent["last_summary"] = summary
    if error is not None:
        agent["last_error"] = error
    elif state in {"assigned", "running", "completed"}:
        agent["last_error"] = None
    _write_agents(config, payload)


def _run_ingest(config: AppConfig) -> dict[str, Any]:
    videos = discover_videos(config.inbox_dir)
    queued = enqueue_new_videos(config)
    return {"discovered": len(videos), "queued": queued}


def _run_clip_generation(config: AppConfig) -> dict[str, Any]:
    job = process_next_job(config)
    if job:
        return {"job": job, "pipeline": job.get("summary") or {}}
    return {"job": None, "pipeline": process_once(config)}


def _run_content_intelligence(config: AppConfig) -> dict[str, Any]:
    index = load_json(config.index_path, {"videos": {}})
    clips = [
        clip
        for video in index.get("videos", {}).values()
        for clip in video.get("clips", [])
    ]
    analyzed = [clip for clip in clips if clip.get("analysis") and "score" in clip]
    missing = [clip.get("id") or clip.get("clip_id") for clip in clips if clip not in analyzed]
    return {"clips": len(clips), "analyzed": len(analyzed), "missing": missing[:20]}


def _run_metadata_indexing(config: AppConfig) -> dict[str, Any]:
    return build_metadata_index(config.root)


def _run_analytics_learning(config: AppConfig) -> dict[str, Any]:
    history_path = config.analytics_dir / "performance_history.json"
    history = load_json(history_path, {"version": 1, "records": []})
    summary, top_patterns = build_learning_outputs(history)
    summary["history_path"] = str(history_path)
    save_json(config.analytics_dir / "learning_summary.json", summary)
    save_json(config.analytics_dir / "top_patterns.json", top_patterns)
    return {"records": len(history.get("records", [])), "learning_summary_path": str(config.analytics_dir / "learning_summary.json")}


def _entry_score(entry: dict[str, Any], metadata_by_clip: dict[str, dict[str, Any]]) -> int:
    base = int(entry.get("score", 0) or 0)
    metadata = metadata_by_clip.get(entry.get("clip_id", ""), {})
    tag_bonus = min(len(metadata.get("semantic_tags", [])), 8)
    label_bonus = min(len(entry.get("scene_labels", [])), 4)
    return base + tag_bonus + label_bonus


def _run_recommendation(config: AppConfig) -> dict[str, Any]:
    queue = load_json(config.queue_path, {"entries": []})
    metadata = load_json(config.analytics_dir / "metadata_index.json", {"items": []})
    metadata_by_clip = {item.get("clip_id", ""): item for item in metadata.get("items", [])}
    ranked = sorted(
        queue.get("entries", []),
        key=lambda entry: (_entry_score(entry, metadata_by_clip), entry.get("clip_id", "")),
        reverse=True,
    )
    recommendations = [
        {
            "rank": index,
            "queue_entry_id": entry.get("id"),
            "clip_id": entry.get("clip_id"),
            "score": _entry_score(entry, metadata_by_clip),
            "base_score": int(entry.get("score", 0) or 0),
            "reason": "highest deterministic local score, metadata tags, and scene labels",
            "clip_path": entry.get("clip_path"),
            "package_path": entry.get("package_path"),
        }
        for index, entry in enumerate(ranked[:10], start=1)
    ]
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "strategy": "deterministic_score_tags_labels_v1",
        "count": len(recommendations),
        "recommendations": recommendations,
    }
    save_json(orchestration_paths(config)["recommendations"], payload)
    return {"recommendations": len(recommendations), "top_clip_id": recommendations[0]["clip_id"] if recommendations else None}


def _run_export(config: AppConfig) -> dict[str, Any]:
    approvals_path = config.queue_dir / "approved_reviews.json"
    if not approvals_path.exists():
        return {"exported": 0, "skipped": True, "reason": "queue/approved_reviews.json not found"}
    return export_approved_posts(config.root, approvals_path=approvals_path)


RUNNERS: dict[str, Callable[[AppConfig], dict[str, Any]]] = {
    "ingest": _run_ingest,
    "clip_generation": _run_clip_generation,
    "content_intelligence": _run_content_intelligence,
    "metadata_indexing": _run_metadata_indexing,
    "analytics_learning": _run_analytics_learning,
    "recommendation": _run_recommendation,
    "export": _run_export,
}


def run_orchestrator(config: AppConfig, task: str = "default", dry_run: bool = False) -> dict[str, Any]:
    ensure_directories(config)
    agents_payload = _load_agents(config)
    for agent in agents_payload["agents"]:
        if agent.get("state") != "disabled":
            agent["state"] = "idle"
            agent["assigned_task"] = None
    _write_agents(config, agents_payload)
    graph = write_orchestration_graph(config)

    run_id = f"orchestration_{utc_now()}"
    _append_activity(config, "orchestrator", "started", f"Started {task} orchestration", {"run_id": run_id, "dry_run": dry_run})
    results: list[dict[str, Any]] = []

    for spec in AGENTS:
        agent = _agent_record(agents_payload, spec.id)
        if agent.get("state") == "disabled" or not agent.get("enabled", True):
            _append_activity(config, spec.id, "disabled", f"{spec.name} is disabled")
            results.append({"agent_id": spec.id, "state": "disabled", "summary": {}})
            continue
        _set_state(config, agents_payload, spec.id, "assigned", assigned_task=task)
        _append_activity(config, spec.id, "assigned", f"{spec.name} assigned {task}")
        if dry_run:
            summary = {"dry_run": True}
            _set_state(config, agents_payload, spec.id, "completed", summary=summary)
            _append_activity(config, spec.id, "completed", f"{spec.name} dry-run completed", summary)
            results.append({"agent_id": spec.id, "state": "completed", "summary": summary})
            continue
        _set_state(config, agents_payload, spec.id, "running", assigned_task=task)
        _append_activity(config, spec.id, "running", f"{spec.name} running {task}")
        try:
            summary = RUNNERS[spec.id](config)
            _set_state(config, agents_payload, spec.id, "completed", summary=summary)
            _append_activity(config, spec.id, "completed", f"{spec.name} completed {task}", summary)
            results.append({"agent_id": spec.id, "state": "completed", "summary": summary})
        except Exception as exc:  # noqa: BLE001 - orchestration must persist local failure detail.
            summary = {"error": str(exc)}
            _set_state(config, agents_payload, spec.id, "failed", summary=summary, error=str(exc))
            _append_activity(config, spec.id, "failed", f"{spec.name} failed {task}: {exc}", summary)
            results.append({"agent_id": spec.id, "state": "failed", "summary": summary})

    final_agents = _load_agents(config)
    completed = sum(1 for result in results if result["state"] == "completed")
    failed = sum(1 for result in results if result["state"] == "failed")
    final_summary = {
        "version": 1,
        "run_id": run_id,
        "updated_at": utc_now(),
        "local_only": True,
        "task": task,
        "execution_mode": "sequential",
        "dry_run": dry_run,
        "completed": completed,
        "failed": failed,
        "results": results,
        "agents_path": str(orchestration_paths(config)["agents"]),
        "activity_path": str(orchestration_paths(config)["activity"]),
        "graph_path": str(orchestration_paths(config)["graph"]),
        "graph_nodes": len(graph.get("nodes", [])),
        "agent_states": {agent["id"]: agent["state"] for agent in final_agents["agents"]},
    }
    _append_activity(config, "orchestrator", "completed", f"Finished {task} orchestration", final_summary)
    return final_summary
