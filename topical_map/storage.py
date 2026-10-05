"""Small JSON storage helpers for project-local data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KEYWORDS_PATH = DATA_DIR / "keywords.json"
SERPS_PATH = DATA_DIR / "serps.json"


def load_json(path: Path, default: Any) -> Any:
    """Load JSON from *path*, returning *default* when it does not exist."""
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, value: Any) -> None:
    """Save *value* as readable UTF-8 JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write("\n")


def load_keywords() -> list[dict[str, Any]]:
    """Load the keyword records used by the app."""
    value = load_json(KEYWORDS_PATH, [])
    return value if isinstance(value, list) else []


def load_serps() -> list[dict[str, Any]]:
    """Load the stored SERP records used by the app."""
    value = load_json(SERPS_PATH, [])
    return value if isinstance(value, list) else []
