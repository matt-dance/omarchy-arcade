"""Live checks for the optional IGDB (Twitch) and SteamGridDB keys.

Results are short status words (ok, invalid, unreachable, missing) so they can
be shown in the overlay and logged without ever echoing a key.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from .http import HttpClient, HttpError
from .igdb import GAMES_URL, TOKEN_URL, _write_cached_token, token_cache_path
from .keys import Keys
from .steamgriddb import BASE as SGDB_BASE

OK = "ok"
INVALID = "invalid"
UNREACHABLE = "unreachable"
MISSING = "missing"

_AUTH_FAILURES = (400, 401, 403)


def _failure(exc: HttpError) -> str:
    return INVALID if exc.status in _AUTH_FAILURES else UNREACHABLE


def check_steamgriddb(keys: Keys, http: HttpClient) -> str:
    if not keys.has_steamgriddb:
        return MISSING
    headers = {"Authorization": f"Bearer {keys.steamgriddb_api_key}"}
    try:
        payload = http.get_json(f"{SGDB_BASE}/search/autocomplete/portal", headers)
    except HttpError as exc:
        return _failure(exc)
    if isinstance(payload, dict) and payload.get("success"):
        return OK
    return INVALID


def check_igdb(keys: Keys, http: HttpClient, cache_dir: Path | None = None) -> str:
    """Fetch a fresh Twitch token, then make one tiny IGDB query with it."""
    if not keys.has_igdb:
        return MISSING
    body = urlencode(
        {
            "client_id": keys.twitch_client_id,
            "client_secret": keys.twitch_client_secret,
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    try:
        data = http.post_json(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    except HttpError as exc:
        return _failure(exc)
    token = str((data or {}).get("access_token") or "").strip() if isinstance(data, dict) else ""
    if not token:
        return INVALID
    headers = {
        "Client-ID": str(keys.twitch_client_id),
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        http.post_json(GAMES_URL, b"fields id; limit 1;", headers)
    except HttpError as exc:
        return _failure(exc)
    try:
        expires_in = int(data.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    _write_cached_token(token_cache_path(cache_dir), token, expires_in)
    return OK


def clear_igdb_token(cache_dir: Path | None = None) -> None:
    try:
        token_cache_path(cache_dir).unlink()
    except FileNotFoundError:
        pass
