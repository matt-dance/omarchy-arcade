"""Steam store appdetails + title search. No API key."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .http import HttpClient, HttpError
from .textutil import best_title_match, parse_year, strip_html

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
STORESEARCH_URL = (
    "https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc=US"
)


def parse_appdetails(payload: Any, appid: int) -> dict[str, Any] | None:
    """Normalize a store appdetails payload. Missing fields stay empty."""
    if not isinstance(payload, dict):
        return None
    entry = payload.get(str(appid)) or payload.get(appid)
    if not isinstance(entry, dict) or not entry.get("success"):
        return None
    data = entry.get("data")
    if not isinstance(data, dict):
        return None

    genres: list[str] = []
    for row in data.get("genres") or []:
        if isinstance(row, dict):
            name = strip_html(str(row.get("description") or row.get("name") or ""))
            if name and name not in genres:
                genres.append(name)

    developers = [
        strip_html(str(x))
        for x in (data.get("developers") or [])
        if str(x).strip()
    ]
    publishers = [
        strip_html(str(x))
        for x in (data.get("publishers") or [])
        if str(x).strip()
    ]

    release = data.get("release_date") or {}
    release_date = ""
    if isinstance(release, dict):
        release_date = strip_html(str(release.get("date") or ""))

    rating = None
    critic = data.get("metacritic")
    if isinstance(critic, dict) and critic.get("score") is not None:
        try:
            score = int(critic["score"])
        except (TypeError, ValueError):
            score = None
        if score is not None:
            rating = {"source": "metacritic", "score": score, "label": str(score)}

    screenshots: list[str] = []
    for row in data.get("screenshots") or []:
        if not isinstance(row, dict):
            continue
        url = row.get("path_thumbnail") or row.get("path_full")
        if url:
            screenshots.append(str(url))

    return {
        "steamAppId": int(data.get("steam_appid") or appid),
        "title": strip_html(str(data.get("name") or "")),
        "description": strip_html(str(data.get("short_description") or "")),
        "genres": genres,
        "developers": developers,
        "publishers": publishers,
        "releaseDate": release_date,
        "releaseYear": parse_year(release_date),
        "rating": rating,
        "screenshotUrls": screenshots[:8],
    }


def fetch_appdetails(appid: int, http: HttpClient) -> dict[str, Any] | None:
    url = APPDETAILS_URL.format(appid=int(appid))
    try:
        payload = http.get_json(url)
    except HttpError:
        return None
    return parse_appdetails(payload, int(appid))


def parse_store_search(payload: Any, title: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    items = payload.get("items") or []
    if not isinstance(items, list):
        return None
    names: list[str] = []
    ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        try:
            appid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        names.append(name)
        ids.append(appid)
    idx = best_title_match(title, names)
    if idx is None:
        return None
    return ids[idx]


def search_appid(title: str, http: HttpClient) -> int | None:
    if not (title or "").strip():
        return None
    url = STORESEARCH_URL.format(term=quote(title.strip()))
    try:
        payload = http.get_json(url)
    except HttpError:
        return None
    return parse_store_search(payload, title)
