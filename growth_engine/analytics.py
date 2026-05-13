from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .index import relative_path, utc_now
from .json_store import load_json_file, save_json_file


METRIC_KEYS = ("views", "likes", "comments", "shares", "saves", "watch_time", "retention_percent")


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_json_file(path, default)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    save_json_file(path, payload)


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _performance_score(metrics: dict[str, Any]) -> int:
    views = max(_number(metrics.get("views")), 1.0)
    engagement = (
        _number(metrics.get("likes"))
        + (_number(metrics.get("comments")) * 2.0)
        + (_number(metrics.get("shares")) * 3.0)
        + (_number(metrics.get("saves")) * 3.0)
    ) / views
    retention = _number(metrics.get("retention_percent")) / 100.0
    watch_bonus = min(_number(metrics.get("watch_time")) / max(views * 8.0, 1.0), 1.0)
    score = (engagement * 420.0) + (retention * 45.0) + (watch_bonus * 15.0)
    return int(round(max(0.0, min(100.0, score))))


def _clip_length_bucket(seconds: float) -> str:
    if seconds < 7:
        return "under_7s"
    if seconds <= 12:
        return "7_to_12s"
    if seconds <= 20:
        return "13_to_20s"
    return "over_20s"


def _posting_pattern(posted_at: str | None) -> str:
    if not posted_at:
        return "unknown"
    # Keep this dependency-free and stable: use the timestamp's date/hour text if present.
    day = posted_at[:10] if len(posted_at) >= 10 else "unknown_day"
    hour = posted_at[11:13] if len(posted_at) >= 13 else "unknown_hour"
    return f"{day}_hour_{hour}"


def _queue_entries_by_id(queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = queue.get("entries", [])
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        by_id[entry.get("id", "")] = entry
        by_id[entry.get("clip_id", "")] = entry
        by_id[entry.get("package_id", "")] = entry
    return {key: value for key, value in by_id.items() if key}


def normalize_import_records(import_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_records = import_payload.get("records", import_payload.get("performance", []))
    if isinstance(raw_records, dict):
        raw_records = [raw_records]
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        metrics = {key: _number(raw.get(key)) for key in METRIC_KEYS}
        records.append(
            {
                "id": raw.get("id") or f"perf_{raw.get('clip_id') or raw.get('queue_entry_id') or len(records) + 1}",
                "queue_entry_id": raw.get("queue_entry_id"),
                "clip_id": raw.get("clip_id"),
                "package_id": raw.get("package_id"),
                "export_id": raw.get("export_id"),
                "posted_at": raw.get("posted_at"),
                "source": raw.get("source", "manual"),
                "notes": raw.get("notes", ""),
                "metrics": metrics,
            }
        )
    return records


def _enrich_record(record: dict[str, Any], queue_lookup: dict[str, dict[str, Any]], root: Path) -> dict[str, Any]:
    entry = (
        queue_lookup.get(str(record.get("queue_entry_id") or ""))
        or queue_lookup.get(str(record.get("clip_id") or ""))
        or queue_lookup.get(str(record.get("package_id") or ""))
        or {}
    )
    package: dict[str, Any] = {}
    if entry.get("package_path"):
        package_path = root / entry["package_path"]
        if package_path.exists():
            package = load_json(package_path)

    predicted = int(entry.get("score", package.get("score", 0)) or 0)
    actual = _performance_score(record["metrics"])
    clip_duration = float(entry.get("analysis", {}).get("clip_duration_seconds", 0.0) or package.get("duration_seconds", 0.0) or 0.0)
    if not clip_duration:
        clip_duration = float(package.get("analysis", {}).get("duration_seconds", 0.0) or 0.0)
    if not clip_duration:
        clip_duration = 8.0

    enriched = {
        **record,
        "queue_entry_id": record.get("queue_entry_id") or entry.get("id"),
        "clip_id": record.get("clip_id") or entry.get("clip_id"),
        "package_id": record.get("package_id") or entry.get("package_id") or package.get("id"),
        "hook": package.get("hook", ""),
        "predicted_hook_score": predicted,
        "actual_performance_score": actual,
        "learning_delta": actual - predicted,
        "scene_labels": package.get("scene_labels", entry.get("scene_labels", [])),
        "hook_moments": package.get("hook_moments", entry.get("hook_moments", [])),
        "clip_length_seconds": clip_duration,
        "clip_length_bucket": _clip_length_bucket(clip_duration),
        "posting_pattern": _posting_pattern(record.get("posted_at")),
        "imported_at": utc_now(),
    }
    return enriched


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _rank_group(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        values = record.get(key, [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if value:
                grouped[str(value)].append(record)
    ranked = []
    for value, items in grouped.items():
        ranked.append(
            {
                "value": value,
                "count": len(items),
                "avg_actual_performance_score": _average([item["actual_performance_score"] for item in items]),
                "avg_learning_delta": _average([item["learning_delta"] for item in items]),
            }
        )
    return sorted(ranked, key=lambda item: (item["avg_actual_performance_score"], item["count"]), reverse=True)


def build_learning_outputs(history: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    records = history.get("records", [])
    rankings = {
        "best_hooks": _rank_group(records, "hook"),
        "best_scene_labels": _rank_group(records, "scene_labels"),
        "best_clip_lengths": _rank_group(records, "clip_length_bucket"),
        "best_posting_patterns": _rank_group(records, "posting_pattern"),
    }
    top_patterns = {
        "updated_at": utc_now(),
        "insights": [
            {
                "type": name,
                "top": values[0] if values else None,
            }
            for name, values in rankings.items()
        ],
        "rankings": rankings,
    }
    summary = {
        "updated_at": utc_now(),
        "record_count": len(records),
        "avg_predicted_hook_score": _average([record["predicted_hook_score"] for record in records]),
        "avg_actual_performance_score": _average([record["actual_performance_score"] for record in records]),
        "avg_learning_delta": _average([record["learning_delta"] for record in records]),
        "recent_records": records[-10:],
    }
    return summary, top_patterns


def import_performance_metrics(root: Path, import_path: Path, history_path: Path | None = None) -> dict[str, Any]:
    project_root = root.resolve()
    queue = load_json(project_root / "queue" / "review_queue.json", {"entries": []})
    queue_lookup = _queue_entries_by_id(queue)
    import_payload = load_json(import_path)
    records = normalize_import_records(import_payload)
    history_file = history_path or project_root / "analytics" / "performance_history.json"
    history = load_json(history_file, {"version": 1, "records": []})

    enriched = [_enrich_record(record, queue_lookup, project_root) for record in records]
    history.setdefault("version", 1)
    history.setdefault("records", [])
    history["records"].extend(enriched)
    history["updated_at"] = utc_now()
    save_json(history_file, history)

    summary, top_patterns = build_learning_outputs(history)
    summary["history_path"] = relative_path(history_file, project_root)
    summary["import_path"] = relative_path(import_path, project_root)
    save_json(project_root / "analytics" / "learning_summary.json", summary)
    save_json(project_root / "analytics" / "top_patterns.json", top_patterns)
    return {
        "imported": len(enriched),
        "history_records": len(history["records"]),
        "history_path": str(history_file),
        "learning_summary_path": str(project_root / "analytics" / "learning_summary.json"),
        "top_patterns_path": str(project_root / "analytics" / "top_patterns.json"),
    }
