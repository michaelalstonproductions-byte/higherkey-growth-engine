from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .analytics import load_json, save_json
from .index import relative_path, utc_now


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "into",
    "the",
    "this",
    "that",
    "what",
    "when",
    "with",
    "your",
}


def optional_ai_status() -> dict[str, Any]:
    return {
        "whisper": {
            "available": bool(shutil.which("whisper")),
            "command": shutil.which("whisper"),
            "enabled_by_default": False,
            "required": False,
        },
        "ocr": {
            "available": bool(shutil.which("tesseract")),
            "command": shutil.which("tesseract"),
            "enabled_by_default": False,
            "required": False,
        },
    }


def maybe_run_whisper(clip_path: Path, output_dir: Path, enabled: bool = False) -> dict[str, Any]:
    command = shutil.which("whisper")
    if not enabled:
        return {"status": "not_enabled", "segments": [], "engine": "whisper_cli_optional"}
    if not command:
        return {"status": "unavailable", "segments": [], "engine": "whisper_cli_optional"}
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [command, str(clip_path), "--output_dir", str(output_dir), "--output_format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        result_path = output_dir / f"{clip_path.stem}.json"
        if result_path.exists():
            payload = load_json(result_path)
            return {"status": "transcribed", "segments": payload.get("segments", []), "engine": "whisper_cli_optional"}
    except Exception as exc:  # noqa: BLE001 - optional local AI must be non-fatal.
        return {"status": "error", "segments": [], "engine": "whisper_cli_optional", "error": str(exc)}
    return {"status": "no_output", "segments": [], "engine": "whisper_cli_optional"}


def maybe_run_ocr(frame_paths: list[Path], enabled: bool = False) -> dict[str, Any]:
    command = shutil.which("tesseract")
    if not enabled:
        return {"status": "not_enabled", "detected_text": [], "engine": "tesseract_optional"}
    if not command:
        return {"status": "unavailable", "detected_text": [], "engine": "tesseract_optional"}
    detected: list[str] = []
    for frame_path in frame_paths:
        try:
            result = subprocess.run([command, str(frame_path), "stdout"], check=True, capture_output=True, text=True)
            text = result.stdout.strip()
            if text:
                detected.append(text)
        except Exception:
            continue
    return {"status": "detected" if detected else "no_text", "detected_text": detected, "engine": "tesseract_optional"}


def _tokens(*parts: Any) -> list[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    cleaned = "".join(char if char.isalnum() else " " for char in text)
    return [token for token in cleaned.split() if len(token) > 2 and token not in STOPWORDS]


def semantic_tags(package: dict[str, Any]) -> list[str]:
    analysis = package.get("analysis", {})
    ocr_text = " ".join(analysis.get("ocr", {}).get("detected_text", []))
    speech_text = " ".join(segment.get("text", "") for segment in analysis.get("speech", {}).get("segments", []))
    counter = Counter(_tokens(package.get("hook"), package.get("caption"), ocr_text, speech_text))
    tags = [tag for tag, _ in counter.most_common(8)]
    tags.extend(package.get("scene_labels", []))
    if package.get("score", 0) >= 50:
        tags.append("high_hook_score")
    if package.get("has_audio"):
        tags.append("audio")
    return sorted(set(tags))


def fallback_embedding(tags: list[str], text: str, dimensions: int = 16) -> list[float]:
    vector = [0.0] * dimensions
    for token in tags + _tokens(text):
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = digest[0] % dimensions
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def similarity_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    tags_a = set(a.get("semantic_tags", []))
    tags_b = set(b.get("semantic_tags", []))
    labels_a = set(a.get("scene_labels", []))
    labels_b = set(b.get("scene_labels", []))
    tag_overlap = len(tags_a & tags_b) / max(len(tags_a | tags_b), 1)
    label_overlap = len(labels_a & labels_b) / max(len(labels_a | labels_b), 1)
    score_proximity = 1.0 - min(abs(a.get("score", 0) - b.get("score", 0)) / 100.0, 1.0)
    embedding = cosine(a.get("embedding", {}).get("vector", []), b.get("embedding", {}).get("vector", []))
    return round((tag_overlap * 0.35) + (label_overlap * 0.25) + (score_proximity * 0.15) + (embedding * 0.25), 4)


def optimized_title(package: dict[str, Any], tags: list[str]) -> str:
    base = package.get("suggested_title") or package.get("hook") or "HigherKey clip"
    theme = next((tag for tag in tags if tag not in set(package.get("scene_labels", []))), "")
    if theme and theme.lower() not in base.lower():
        return f"{base}: {theme.replace('_', ' ').title()}"[:90]
    return str(base)[:90]


def _cluster_key(item: dict[str, Any]) -> str:
    labels = item.get("scene_labels", [])
    tags = item.get("semantic_tags", [])
    primary = labels[0] if labels else "general"
    secondary = tags[0] if tags else "untagged"
    return f"{primary}_{secondary}"


def build_metadata_index(root: Path, enable_whisper: bool = False, enable_ocr: bool = False) -> dict[str, Any]:
    project_root = root.resolve()
    queue = load_json(project_root / "queue" / "review_queue.json", {"entries": []})
    items: list[dict[str, Any]] = []

    for entry in queue.get("entries", []):
        package_path = entry.get("package_path")
        if not package_path:
            continue
        package_file = project_root / package_path
        if not package_file.exists():
            continue
        package = load_json(package_file)
        clip_path = project_root / package.get("clip_path", entry.get("clip_path", ""))
        transcript = maybe_run_whisper(clip_path, project_root / "out" / "local_ai" / "transcripts", enable_whisper)
        ocr = maybe_run_ocr([], enable_ocr)
        analysis = package.get("analysis", {})
        if transcript["status"] not in {"not_enabled", "unavailable"}:
            analysis.setdefault("speech", {}).update(transcript)
        if ocr["status"] not in {"not_enabled", "unavailable"}:
            analysis.setdefault("ocr", {}).update(ocr)
        package["analysis"] = analysis
        tags = semantic_tags(package)
        text = " ".join([package.get("hook", ""), package.get("caption", ""), " ".join(tags)])
        item = {
            "clip_id": package.get("clip_id"),
            "queue_entry_id": entry.get("id"),
            "package_id": package.get("id"),
            "clip_path": package.get("clip_path"),
            "package_path": package_path,
            "hook": package.get("hook", ""),
            "caption": package.get("caption", ""),
            "semantic_tags": tags,
            "scene_labels": package.get("scene_labels", []),
            "hook_moments": package.get("hook_moments", []),
            "score": package.get("score", entry.get("score", 0)),
            "optimized_title": optimized_title(package, tags),
            "original_title": package.get("suggested_title", ""),
            "embedding": {
                "status": "deterministic_local_fallback",
                "model": "hashing_vector_v1",
                "dimensions": 16,
                "vector": fallback_embedding(tags, text),
            },
            "optional_ai": {
                "whisper": transcript,
                "ocr": ocr,
            },
            "search_text": text.lower(),
        }
        items.append(item)

    for item in items:
        related = []
        for other in items:
            if other["clip_id"] == item["clip_id"]:
                continue
            score = similarity_score(item, other)
            if score > 0:
                related.append({"clip_id": other["clip_id"], "similarity": score})
        item["similar_clips"] = sorted(related, key=lambda value: value["similarity"], reverse=True)[:5]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_cluster_key(item)].append(item)
    clusters = []
    for index, (key, cluster_items) in enumerate(sorted(grouped.items()), start=1):
        tag_counts = Counter(tag for item in cluster_items for tag in item["semantic_tags"])
        cluster_id = f"cluster_{index:03d}"
        for item in cluster_items:
            item["cluster_id"] = cluster_id
        clusters.append(
            {
                "id": cluster_id,
                "key": key,
                "clip_ids": [item["clip_id"] for item in cluster_items],
                "representative_tags": [tag for tag, _ in tag_counts.most_common(6)],
                "topic_summary": ", ".join(tag for tag, _ in tag_counts.most_common(3)) or key,
            }
        )

    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "optional_ai_status": optional_ai_status(),
        "count": len(items),
        "items": items,
        "clusters": clusters,
    }
    save_json(project_root / "analytics" / "metadata_index.json", payload)
    return {
        "indexed": len(items),
        "clusters": len(clusters),
        "metadata_index_path": str(project_root / "analytics" / "metadata_index.json"),
        "optional_ai_status": payload["optional_ai_status"],
    }
