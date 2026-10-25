"""IGDB via Twitch client-credentials. Active only when both keys are set."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..paths import arcade_cache_dir
from .http import HttpClient, HttpError
from .keys import Keys
from .textutil import best_title_match, parse_year, strip_html

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GAMES_URL = "https://api.igdb.com/v4/games"
IMAGE_BASE = "https://images.igdb.com/igdb/image/upload"


def token_cache_path(cache_dir: Path | None = None) -> Path:
    base = cache_dir if cache_dir is not None else arcade_cache_dir()
    return base / "igdb_token.json"


def _read_cached_token(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    token = str(data.get("access_token") or "").strip()
    try:
        expires = float(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires = 0
    if not token or expires < time.time() + 60:
        return None
    return token


def _write_cached_token(path: Path, token: str, expires_in: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": token,
        "expires_at": time.time() + max(60, int(expires_in or 0)),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def fetch_token(
    keys: Keys,
    http: HttpClient,
    cache_dir: Path | None = None,
) -> str | None:
    if not keys.has_igdb:
        return None
    path = token_cache_path(cache_dir)
    cached = _read_cached_token(path)
    if cached:
        return cached
    body = urlencode(
        {
            "client_id": keys.twitch_client_id,
            "client_secret": keys.twitch_client_secret,
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        data = http.post_json(TOKEN_URL, body, headers)
    except HttpError:
        return None
    if not isinstance(data, dict):
        return None
    token = str(data.get("access_token") or "").strip()
    if not token:
        return None
    try:
        expires_in = int(data.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    _write_cached_token(path, token, expires_in)
    return token


def _image_url(image_id: str, size: str) -> str:
    return f"{IMAGE_BASE}/{size}/{image_id}.jpg"


def parse_games(payload: Any, title: str) -> dict[str, Any] | None:
    if not isinstance(payload, list) or not payload:
        return None
    names = [str(row.get("name") or "") for row in payload if isinstance(row, dict)]
    idx = best_title_match(title, names)
    if idx is None:
        # First result is IGDB's search rank when names are too messy.
        idx = 0
    row = payload[idx]
    if not isinstance(row, dict):
        return None

    genres: list[str] = []
    for g in row.get("genres") or []:
        if isinstance(g, dict):
            name = strip_html(str(g.get("name") or ""))
            if name and name not in genres:
                genres.append(name)

    developers: list[str] = []
    publishers: list[str] = []
    for company in row.get("involved_companies") or []:
        if not isinstance(company, dict):
            continue
        info = company.get("company") or {}
        name = ""
        if isinstance(info, dict):
            name = strip_html(str(info.get("name") or ""))
        if not name:
            continue
        if company.get("developer") and name not in developers:
            developers.append(name)
        if company.get("publisher") and name not in publishers:
            publishers.append(name)

    rating = None
    for key, source in (("aggregated_rating", "igdb"), ("total_rating", "igdb")):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            score = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        rating = {"source": source, "score": score, "label": str(score)}
        break

    screenshots: list[str] = []
    for shot in row.get("screenshots") or []:
        if isinstance(shot, dict) and shot.get("image_id"):
            screenshots.append(_image_url(str(shot["image_id"]), "t_screenshot_med"))

    cover_url = None
    cover = row.get("cover")
    if isinstance(cover, dict) and cover.get("image_id"):
        cover_url = _image_url(str(cover["image_id"]), "t_cover_big")

    release = row.get("first_release_date")
    return {
        "title": strip_html(str(row.get("name") or title)),
        "description": strip_html(str(row.get("summary") or "")),
        "genres": genres,
        "developers": developers,
        "publishers": publishers,
        "releaseYear": parse_year(release),
        "releaseDate": str(parse_year(release) or ""),
        "rating": rating,
        "screenshotUrls": screenshots[:8],
        "coverUrl": cover_url,
    }


def fetch_game(
    title: str,
    keys: Keys,
    http: HttpClient,
    cache_dir: Path | None = None,
) -> dict[str, Any] | None:
    token = fetch_token(keys, http, cache_dir=cache_dir)
    if not token or not keys.twitch_client_id:
        return None
    safe_title = (title or "").replace('"', "")
    body = (
        f'search "{safe_title}"; '
        "fields name,summary,genres.name,involved_companies.company.name,"
        "involved_companies.developer,involved_companies.publisher,"
        "first_release_date,aggregated_rating,total_rating,"
        "screenshots.image_id,cover.image_id; "
        "limit 8;"
    ).encode("utf-8")
    headers = {
        "Client-ID": keys.twitch_client_id,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        payload = http.post_json(GAMES_URL, body, headers)
    except HttpError:
        return None
    return parse_games(payload, title)
