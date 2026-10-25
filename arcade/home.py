"""Home shelf, badges, and playtime helpers (mirrors ArcadeModel.js)."""

from __future__ import annotations

import re
from typing import Any

_CACHE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


SOURCE_LABELS = {
    "steam": "Steam",
    "heroic": "Heroic",
    "legendary": "Legendary",
    "lutris": "Lutris",
    "bottles": "Bottles",
    "itch": "itch.io",
    "gfn": "GeForce NOW",
    "desktop": "Desktop",
    "webapp": "Cloud",
    "retroarch": "RetroArch",
    "roms": "ROMs",
    "moonlight": "Moonlight",
    "gog": "GOG",
    "epic": "Epic",
    "amazon": "Amazon",
}

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def cache_stem(game_id: str | None) -> str:
    """Map a game id to the metadata filename stem. Mirrors ArcadeModel.js cacheStem()."""
    stem = _CACHE_STEM.sub("_", str(game_id or "").strip())
    return stem or "unknown"


def source_label(source: str | None) -> str:
    if not source:
        return ""
    return SOURCE_LABELS.get(str(source).casefold(), str(source))


RECENT_LIMIT = 10


def _title_key(g: dict[str, Any]) -> str:
    return str(g.get("sortTitle") or g.get("title") or "").casefold()


def home_shelf(games: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Recently played (newest, capped), then favorites by title, then the rest.

    Hidden games are left out. Mirrors ArcadeModel.js homeShelf().
    """
    items = [g for g in (games or []) if g and not g.get("hidden")]
    played = [g for g in items if g.get("lastPlayed")]
    unplayed = [g for g in items if not g.get("lastPlayed")]
    played.sort(key=_title_key)
    played.sort(key=lambda g: str(g.get("lastPlayed") or ""), reverse=True)
    unplayed.sort(key=_title_key)
    recent = played[:RECENT_LIMIT]
    remaining = played[RECENT_LIMIT:] + unplayed
    favorites = sorted((g for g in remaining if g.get("favorite")), key=_title_key)
    rest = [g for g in remaining if not g.get("favorite")]
    return recent + favorites + rest


def play_on_choices(game: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not game:
        return []
    out = [
        {
            "id": game.get("id"),
            "source": game.get("source"),
            "store": game.get("store"),
            "title": game.get("title"),
            "launch": game.get("launch"),
            "track": game.get("track"),
            "label": source_label(game.get("source")),
        }
    ]
    for extra in game.get("alsoOn") or []:
        if not extra or isinstance(extra, str):
            continue
        if _is_wrapper_also_on(extra):
            continue
        out.append(
            {
                "id": extra.get("id") or game.get("id"),
                "source": extra.get("source") or "",
                "store": extra.get("store"),
                "title": extra.get("title") or game.get("title"),
                "launch": extra.get("launch"),
                "track": extra.get("track"),
                "label": source_label(extra.get("source")),
            }
        )
    return out


def source_badges(game: dict[str, Any] | None) -> list[str]:
    """Primary source, store, and merged Play on… sources."""
    if not game:
        return []
    badges: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if not label or label in seen:
            return
        seen.add(label)
        badges.append(label)

    add(source_label(game.get("source")))
    store = game.get("store")
    if store:
        add(source_label(store))
    for extra in game.get("alsoOn") or []:
        if not extra or isinstance(extra, str):
            continue
        if _is_wrapper_also_on(extra):
            continue
        label = source_label(extra.get("source"))
        if label and label not in seen:
            add(f"Play on {label}")
    return badges


def _is_wrapper_also_on(extra: dict[str, Any]) -> bool:
    """Hide Steam-generated .desktop wrappers from Play on… badges."""
    source = str(extra.get("source") or "")
    extra_id = str(extra.get("id") or "")
    if extra_id.startswith("desktop:steam:") or extra_id.startswith("steam_app_"):
        return True
    launch = extra.get("launch") or {}
    value = launch.get("value") if isinstance(launch, dict) else ""
    text = value if isinstance(value, str) else " ".join(str(p) for p in (value or []))
    if "steam://rungameid/" in text:
        return True
    track = extra.get("track") or {}
    if source == "desktop" and isinstance(track, dict) and track.get("steamAppId"):
        return True
    return source == "desktop" and "steam://rungameid/" in extra_id


def has_play_on(game: dict[str, Any] | None) -> bool:
    return len(play_on_choices(game)) > 1


def format_playtime(minutes: Any) -> str:
    if minutes is None or minutes == "":
        return ""
    try:
        n = float(minutes)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    if n < 60:
        return f"{int(round(n))} min"
    hours = n / 60.0
    if hours < 10:
        return f"{round(hours, 1):g} h"
    return f"{int(round(hours))} h"


def format_last_played(iso: str | None) -> str:
    if not iso:
        return ""
    day = str(iso)[:10]
    if len(day) < 10 or day[4] != "-" or day[7] != "-":
        return str(iso)
    try:
        year = day[0:4]
        month = int(day[5:7])
        d = int(day[8:10])
    except ValueError:
        return day
    if month < 1 or month > 12 or d < 1:
        return day
    return f"{_MONTHS[month - 1]} {d}, {year}"


def play_meta(game: dict[str, Any] | None) -> str:
    if not game:
        return ""
    last = game.get("lastPlayed")
    if last:
        pretty = format_last_played(str(last))
        return f"Last played {pretty}" if pretty else ""
    minutes = game.get("playtimeMinutes")
    if minutes is not None and minutes != "":
        pretty = format_playtime(minutes)
        return f"{pretty} played" if pretty else ""
    return ""


def hero_url(game: dict[str, Any] | None) -> str:
    if not game:
        return ""
    art = game.get("art") or {}
    if isinstance(art, dict) and art.get("hero"):
        return str(art["hero"])
    return ""


def cover_url(game: dict[str, Any] | None, meta: dict[str, Any] | None = None) -> str:
    if meta:
        art = meta.get("art") or {}
        if isinstance(art, dict) and art.get("cover"):
            return str(art["cover"])
    if not game:
        return ""
    art = game.get("art") or {}
    if isinstance(art, dict) and art.get("cover"):
        return str(art["cover"])
    return ""


def is_icon_only(game: dict[str, Any] | None) -> bool:
    if not game:
        return False
    art = game.get("art") or {}
    return bool(isinstance(art, dict) and art.get("iconOnly"))


def has_meta_cover(meta: dict[str, Any] | None) -> bool:
    if not meta:
        return False
    art = meta.get("art") or {}
    return bool(isinstance(art, dict) and art.get("cover"))


def lookup_meta(game: dict[str, Any] | None, meta_by_id: dict[str, Any] | None) -> dict[str, Any] | None:
    if not game or not game.get("id") or not meta_by_id:
        return None
    found = meta_by_id.get(game.get("id"))
    return found if isinstance(found, dict) else None


def remember_meta(meta_by_id: dict[str, Any] | None, meta: dict[str, Any] | None) -> dict[str, Any]:
    next_map = dict(meta_by_id or {})
    if meta and meta.get("id"):
        next_map[str(meta["id"])] = meta
    return next_map


def is_small_art(
    game: dict[str, Any] | None,
    implicit_w: float = 0,
    implicit_h: float = 0,
    meta: dict[str, Any] | None = None,
) -> bool:
    """True when the card should show a small icon, not cropped box art."""
    if has_meta_cover(meta):
        return False
    width = float(implicit_w or 0)
    height = float(implicit_h or 0)
    if width > 0 or height > 0:
        return max(width, height) < 256
    return is_icon_only(game)
