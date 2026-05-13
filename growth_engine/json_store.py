from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def corrupt_copy_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(":", "").replace("+", "Z")
    return path.with_name(f"{path.name}.corrupt-{stamp}")


def load_json_file(path: Path, default: dict[str, Any] | None = None, copy_corrupt: bool = True) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        if copy_corrupt:
            try:
                shutil.copy2(path, corrupt_copy_path(path))
            except OSError:
                pass
        return default or {}


def save_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
