"""SteamGridDB art (grid / hero / logo). Active only when an API key is set."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .http import HttpClient, HttpError
from .keys import Keys
from .textutil import best_title_match

BASE = "https://www.steamgriddb.com/api/v2"


def _auth(keys: Keys) -> dict[str, str] | None:
    if not keys.has_steamgriddb or not keys.steamgriddb_api_key:
        return None
    return {"Authorization": f"Bearer {keys.steamgriddb_api_key}"}


def _first_url(payload: Any) -> str | None:
    if not isinstance(payload, dict) or not payload.get("success"):
        return None
    rows = payload.get("data") or []
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    url = first.get("url") or first.get("thumb")
    return str(url) if url else None


def _get_image(http: HttpClient, url: str, headers: dict[str, str]) -> str | None:
    try:
        payload = http.get_json(url, headers)
    except HttpError:
        return None
    return _first_url(payload)


def parse_search(payload: Any, title: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return None
    names: list[str] = []
    ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        try:
            gid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        names.append(name)
        ids.append(gid)
    idx = best_title_match(title, names)
    if idx is None:
        return None
    return ids[idx]


def search_game_id(title: str, keys: Keys, http: HttpClient) -> int | None:
    headers = _auth(keys)
    if not headers or not title.strip():
        return None
    url = f"{BASE}/search/autocomplete/{quote(title.strip())}"
    try:
        payload = http.get_json(url, headers)
    except HttpError:
        return None
    return parse_search(payload, title)


def fetch_art(
    *,
    steam_app_id: int | None,
    title: str,
    keys: Keys,
    http: HttpClient,
) -> dict[str, str]:
    """Return remote URLs for cover/hero/logo when available."""
    headers = _auth(keys)
    if not headers:
        return {}
    out: dict[str, str] = {}
    if steam_app_id:
        cover = _get_image(
            http,
            f"{BASE}/grids/steam/{int(steam_app_id)}?dimensions=600x900&types=static",
            headers,
        )
        if not cover:
            cover = _get_image(http, f"{BASE}/grids/steam/{int(steam_app_id)}", headers)
        hero = _get_image(http, f"{BASE}/heroes/steam/{int(steam_app_id)}", headers)
        logo = _get_image(http, f"{BASE}/logos/steam/{int(steam_app_id)}", headers)
        if cover:
            out["cover"] = cover
        if hero:
            out["hero"] = hero
        if logo:
            out["logo"] = logo
        if out:
            return out

    game_id = search_game_id(title, keys, http)
    if not game_id:
        return {}
    cover = _get_image(
        http,
        f"{BASE}/grids/game/{game_id}?dimensions=600x900&types=static",
        headers,
    ) or _get_image(http, f"{BASE}/grids/game/{game_id}", headers)
    hero = _get_image(http, f"{BASE}/heroes/game/{game_id}", headers)
    logo = _get_image(http, f"{BASE}/logos/game/{game_id}", headers)
    if cover:
        out["cover"] = cover
    if hero:
        out["hero"] = hero
    if logo:
        out["logo"] = logo
    return out
