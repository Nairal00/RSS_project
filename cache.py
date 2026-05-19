from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).parent / "cache.json"


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"[WARNING] cache.json is corrupted — starting with empty cache.")
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_cached(cache: dict[str, Any], url: str) -> dict[str, Any] | None:
    return cache.get(url)


def update_cache(cache: dict[str, Any], url: str, data: dict[str, Any]) -> None:
    cache[url] = data
