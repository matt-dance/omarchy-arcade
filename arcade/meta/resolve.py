"""Merge metadata sources into one cached record per game."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..model import Game
from ..paths import meta_cache_dir, steam_roots
from ..steam_local import playtime_for_appid
from .cache import (
    META_TTL_DAYS,
    file_uri,
    is_fresh,
    load_cached,
    meta_asset_dir,
    write_cached,
)
from .http import HttpClient
from .igdb import fetch_game as fetch_igdb
from .keys import Keys, load_keys
from .launchers import (
    is_launcher,
    launcher_cache_looks_like_a_game,
    launcher_description,
)
from .protondb import fetch_summary as fetch_protondb
from .steam import fetch_appdetails, search_appid
from .steamgriddb import fetch_art as fetch_sgdb_art
from .textutil import iso_now

MAX_SCREENSHOTS = 4

# GFN / store titles that should try a Steam store search when no appid is set.
_STEAMISH_STORES = {"steam", "gfn"}


def _as_game(game: Game | dict[str, Any]) -> dict[str, Any]:
    if isinstance(game, Game):
        return game.to_dict()
    return dict(game)


def steam_app_id_of(game: dict[str, Any]) -> int | None:
    raw = game.get("steamAppId") or game.get("steam_app_id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    for extra in game.get("alsoOn") or []:
        if not isinstance(extra, dict):
            continue
        raw = extra.get("steamAppId") or extra.get("steam_app_id")
        if not raw:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def should_search_steam(game: dict[str, Any]) -> bool:
    if is_launcher(game):
        return False
    if steam_app_id_of(game):
        return False
    source = str(game.get("source") or "").casefold()
    store = str(game.get("store") or "").casefold()
    if source == "steam" or store == "steam":
        return True
    if source == "gfn" and store in _STEAMISH_STORES:
        return True
    return False


def art_is_weak(art: dict[str, Any] | None) -> bool:
    if not art:
        return True
    cover = str(art.get("cover") or "")
    icon = str(art.get("icon") or "")
    if not cover:
        return True
    if icon and cover == icon:
        return True
    low = cover.casefold()
    if "/icons/" in low or low.endswith((".ico", ".svg")):
        return True
    return False


def _merge_fill(base: dict[str, Any], incoming: dict[str, Any], *, overwrite: bool = False) -> None:
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if overwrite or base.get(key) in (None, "", [], {}):
            base[key] = value


def _download_images(
    game_id: str,
    urls: list[str],
    http: HttpClient,
    cache_dir: Path,
    prefix: str,
    limit: int,
) -> list[str]:
    dest_dir = meta_asset_dir(game_id, cache_dir)
    saved: list[str] = []
    for i, url in enumerate(urls[:limit]):
        dest = dest_dir / f"{prefix}{i}.jpg"
        if dest.is_file() or http.download(url, dest):
            saved.append(file_uri(dest))
    return saved


def _download_named(
    game_id: str,
    url: str | None,
    http: HttpClient,
    cache_dir: Path,
    name: str,
) -> str | None:
    if not url:
        return None
    dest = meta_asset_dir(game_id, cache_dir) / name
    if dest.is_file() or http.download(url, dest):
        return file_uri(dest)
    return None


def _apply_launcher_meta(record: dict[str, Any], game: dict[str, Any]) -> None:
    if not is_launcher(game):
        return
    copy = launcher_description(game)
    if copy:
        record["description"] = copy
    used = list(record.get("sourcesUsed") or [])
    if "launcher" not in used:
        used.append("launcher")
    record["sourcesUsed"] = used


def _empty_record(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "id": game.get("id"),
        "title": game.get("title"),
        "fetchedAt": None,
        "ttlDays": META_TTL_DAYS,
        "steamAppId": steam_app_id_of(game),
        "description": "",
        "genres": [],
        "developers": [],
        "publishers": [],
        "releaseDate": "",
        "releaseYear": None,
        "rating": None,
        "playtimeMinutes": game.get("playtimeMinutes"),
        "lastPlayed": game.get("lastPlayed"),
        "proton": None,
        "screenshots": [],
        "art": {},
        "sourcesUsed": [],
        "errors": [],
    }


def resolve_game(
    game: Game | dict[str, Any],
    *,
    force: bool = False,
    offline: bool = False,
    http: HttpClient | None = None,
    keys: Keys | None = None,
    cache_dir: Path | None = None,
    steam_library_roots: list[Path] | None = None,
    now=None,
) -> dict[str, Any]:
    """Return metadata for one game, using cache when fresh.

    Network work is skipped when `offline` is set or a source is missing.
    Local Steam playtime is always overlaid from disk when an appid is known.
    """
    data = _as_game(game)
    game_id = str(data.get("id") or "")
    cache = cache_dir if cache_dir is not None else meta_cache_dir()
    existing = load_cached(game_id, cache) if game_id else None
    # A prior IGDB substring match can pin Warcraft II onto Battle.net.
    if existing and is_launcher(data) and launcher_cache_looks_like_a_game(existing):
        existing = None
    record = _empty_record(data)
    if existing:
        _merge_fill(record, existing, overwrite=True)
        record["id"] = game_id
        record["errors"] = []

    if existing and not force and is_fresh(existing, now=now):
        _apply_launcher_meta(record, data)
        _overlay_playtime(record, steam_library_roots)
        record["fresh"] = True
        return record

    if offline:
        _apply_launcher_meta(record, data)
        _overlay_playtime(record, steam_library_roots)
        record["fresh"] = bool(existing and is_fresh(existing, now=now))
        return record

    client = http or HttpClient()
    creds = keys if keys is not None else load_keys()
    if is_launcher(data):
        _apply_launcher_meta(record, data)
    used: list[str] = list(record.get("sourcesUsed") or [])
    errors: list[str] = []

    appid = steam_app_id_of(data) or record.get("steamAppId")
    if not appid and should_search_steam(data):
        found = search_appid(str(data.get("title") or ""), client)
        if found:
            appid = found
            record["steamAppId"] = found
            used.append("steam-search")
        else:
            errors.append("steam-search: no match")

    if appid:
        steam_meta = fetch_appdetails(int(appid), client)
        if steam_meta:
            _merge_fill(record, steam_meta, overwrite=True)
            used.append("steam")
        else:
            errors.append("steam: unavailable")
        proton = fetch_protondb(int(appid), client)
        if proton:
            record["proton"] = proton
            used.append("protondb")
        else:
            errors.append("protondb: unavailable")

    needs_igdb = creds.has_igdb and not is_launcher(data) and (
        not record.get("description") or not appid
    )
    if needs_igdb:
        igdb = fetch_igdb(
            str(data.get("title") or ""),
            creds,
            client,
            cache_dir=cache,
        )
        if igdb:
            cover_url = igdb.pop("coverUrl", None)
            _merge_fill(record, igdb, overwrite=False)
            if cover_url and not record.get("art"):
                record.setdefault("_remoteArt", {})["cover"] = cover_url
            used.append("igdb")
        else:
            errors.append("igdb: unavailable")

    remote_art: dict[str, str] = {}
    if creds.has_steamgriddb:
        sgdb = fetch_sgdb_art(
            steam_app_id=int(appid) if appid else None,
            title=str(data.get("title") or ""),
            keys=creds,
            http=client,
        )
        if sgdb:
            remote_art.update(sgdb)
            used.append("steamgriddb")
        else:
            errors.append("steamgriddb: unavailable")
    extra_art = record.pop("_remoteArt", None)
    if isinstance(extra_art, dict):
        for slot, url in extra_art.items():
            remote_art.setdefault(slot, url)

    if game_id:
        shots = _download_images(
            game_id,
            list(record.pop("screenshotUrls", None) or []),
            client,
            cache,
            "ss",
            MAX_SCREENSHOTS,
        )
        if shots:
            record["screenshots"] = shots
        art: dict[str, str] = dict(record.get("art") or {})
        for slot, filename in (("cover", "cover.jpg"), ("hero", "hero.jpg"), ("logo", "logo.png")):
            uri = _download_named(game_id, remote_art.get(slot), client, cache, filename)
            if uri:
                art[slot] = uri
        record["art"] = art

    record.pop("screenshotUrls", None)
    record["fetchedAt"] = iso_now()
    record["ttlDays"] = META_TTL_DAYS
    record["sourcesUsed"] = list(dict.fromkeys(used))
    record["errors"] = errors
    record["fresh"] = True
    _overlay_playtime(record, steam_library_roots)
    if game_id:
        persist = {k: v for k, v in record.items() if k != "fresh"}
        write_cached(game_id, persist, cache)
    return record


def _overlay_playtime(record: dict[str, Any], roots: list[Path] | None) -> None:
    appid = record.get("steamAppId")
    if not appid:
        return
    try:
        appid_i = int(appid)
    except (TypeError, ValueError):
        return
    minutes, last = playtime_for_appid(appid_i, roots if roots is not None else steam_roots())
    if minutes is not None:
        record["playtimeMinutes"] = minutes
    if last:
        record["lastPlayed"] = last
    if minutes is not None or last:
        used = list(record.get("sourcesUsed") or [])
        if "local" not in used:
            used.append("local")
        record["sourcesUsed"] = used


def resolve_library(
    games: list[Any],
    *,
    ids: list[str] | None = None,
    limit: int | None = None,
    force: bool = False,
    offline: bool = False,
    http: HttpClient | None = None,
    keys: Keys | None = None,
    cache_dir: Path | None = None,
    steam_library_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Resolve a batch of games. Prefer recently played when no ids given."""
    wanted = set(ids or [])
    rows = [_as_game(g) for g in games]
    if wanted:
        rows = [g for g in rows if g.get("id") in wanted]
    else:
        rows.sort(key=lambda g: str(g.get("lastPlayed") or ""), reverse=True)
    if limit is not None:
        rows = rows[: max(0, int(limit))]

    updated: list[str] = []
    errors: list[str] = []
    art_updated = 0
    creds = keys if keys is not None else load_keys()
    client = http or HttpClient()
    cache = cache_dir if cache_dir is not None else meta_cache_dir()

    for game in rows:
        gid = str(game.get("id") or "")
        try:
            meta = resolve_game(
                game,
                force=force,
                offline=offline,
                http=client,
                keys=creds,
                cache_dir=cache,
                steam_library_roots=steam_library_roots,
            )
        except Exception as exc:  # noqa: BLE001 — one game must not abort the batch
            errors.append(f"{gid}: {exc.__class__.__name__}")
            continue
        if gid:
            updated.append(gid)
        errors.extend(f"{gid}: {e}" for e in (meta.get("errors") or []))
        if meta.get("art") and art_is_weak(game.get("art")):
            game_art = game.setdefault("art", {})
            for slot in ("cover", "hero", "logo"):
                if meta["art"].get(slot):
                    game_art[slot] = meta["art"][slot]
                    art_updated += 1

    return {
        "updated": len(updated),
        "ids": updated,
        "artUpdated": art_updated,
        "errors": errors,
        "keys": creds.redacted(),
        "games": rows,
    }


def apply_art_to_library(
    library: dict[str, Any],
    resolved: dict[str, Any],
) -> int:
    """Copy improved SGDB/IGDB art onto library.json game rows. Returns count."""
    by_id = {g.get("id"): g for g in resolved.get("games") or [] if isinstance(g, dict)}
    changed = 0
    for game in library.get("games") or []:
        if not isinstance(game, dict):
            continue
        src = by_id.get(game.get("id"))
        if not src:
            continue
        if not art_is_weak(game.get("art")):
            continue
        art = src.get("art") or {}
        if not art:
            continue
        game.setdefault("art", {})
        for slot in ("cover", "hero", "logo"):
            if art.get(slot) and game["art"].get(slot) != art[slot]:
                game["art"][slot] = art[slot]
                changed += 1
        if game["art"].get("cover") and game["art"].get("iconOnly"):
            game["art"]["iconOnly"] = False
            changed += 1
    return changed
