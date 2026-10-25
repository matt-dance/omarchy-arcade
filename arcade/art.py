"""SteamGridDB lookup helpers (by Steam appid or title)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .model import normalize_title

Fetcher = Callable[[urllib.request.Request, float], Any]


def _default_open(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout)


def sgdb_json(url: str, key: str, timeout: float = 15.0, opener: Fetcher | None = None) -> Any:
    opener = opener or _default_open
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with opener(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError):
        return None


def search_sgdb_game_id(title: str, key: str, opener: Fetcher | None = None) -> int | None:
    """Resolve a SteamGridDB game id by title. Requires a verified name match."""
    q = (title or "").strip()
    if not q or not key:
        return None
    url = "https://www.steamgriddb.com/api/v2/search/autocomplete/" + urllib.parse.quote(q)
    data = sgdb_json(url, key, opener=opener)
    rows = (data.get("data") or []) if isinstance(data, dict) else []
    want = normalize_title(q)
    if not want:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or ""
        if normalize_title(str(name)) != want:
            continue
        try:
            return int(row.get("id"))
        except (TypeError, ValueError):
            continue
    return None


def fetch_sgdb_image(
    kind: str,
    lookup: tuple[str, int],
    key: str,
    dest: Path,
    dimensions: str,
    opener: Fetcher | None = None,
) -> str | None:
    """kind is grids|heroes. lookup is ('steam', appid) or ('game', sgdb_id)."""
    scope, ident = lookup
    url = (
        f"https://www.steamgriddb.com/api/v2/{kind}/{scope}/{ident}"
        f"?dimensions={dimensions}&types=static"
    )
    data = sgdb_json(url, key, opener=opener)
    rows = (data.get("data") or []) if isinstance(data, dict) else []
    if not rows:
        return None
    image_url = rows[0].get("url")
    if not image_url:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or _default_open
    req = urllib.request.Request(image_url)
    try:
        with opener(req, 30.0) as img:
            dest.write_bytes(img.read())
    except (urllib.error.URLError, TimeoutError, OSError, TypeError):
        return None
    return dest.as_uri()
