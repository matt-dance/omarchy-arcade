"""On-disk metadata cache: ~/.cache/matt-dance.arcade/meta/<id>.json + images."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..paths import meta_cache_dir
from .textutil import parse_iso

META_TTL_DAYS = 14
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def cache_stem(game_id: str) -> str:
    stem = _SAFE.sub("_", str(game_id or "").strip())
    return stem or "unknown"


def meta_json_path(game_id: str, cache_dir: Path | None = None) -> Path:
    base = cache_dir if cache_dir is not None else meta_cache_dir()
    return base / f"{cache_stem(game_id)}.json"


def meta_asset_dir(game_id: str, cache_dir: Path | None = None) -> Path:
    base = cache_dir if cache_dir is not None else meta_cache_dir()
    return base / cache_stem(game_id)


def is_fresh(
    meta: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    ttl_days: int = META_TTL_DAYS,
) -> bool:
    if not meta:
        return False
    fetched = parse_iso(meta.get("fetchedAt"))
    if fetched is None:
        return False
    try:
        days = int(meta.get("ttlDays") or ttl_days)
    except (TypeError, ValueError):
        days = ttl_days
    current = now or datetime.now(timezone.utc)
    return current - fetched < timedelta(days=max(1, days))


def cached_art_map(
    games: list[Any],
    cache_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """id → {id, art} for every library row that already has cached cover/hero/logo."""
    out: dict[str, dict[str, Any]] = {}
    for game in games or []:
        if isinstance(game, dict):
            game_id = str(game.get("id") or "")
        else:
            game_id = str(getattr(game, "id", "") or "")
        if not game_id:
            continue
        meta = load_cached(game_id, cache_dir)
        if not meta:
            continue
        art = meta.get("art") or {}
        if not isinstance(art, dict):
            continue
        slots = {key: art[key] for key in ("cover", "hero", "logo") if art.get(key)}
        if not slots:
            continue
        out[game_id] = {"id": game_id, "art": slots}
    return out


def load_cached(game_id: str, cache_dir: Path | None = None) -> dict[str, Any] | None:
    path = meta_json_path(game_id, cache_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_cached(
    game_id: str,
    payload: dict[str, Any],
    cache_dir: Path | None = None,
) -> Path:
    path = meta_json_path(game_id, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()
