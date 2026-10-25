"""Unified game model and library merge helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_TITLE_STRIP = re.compile(r"[^a-z0-9]+")

# Display prefixes added by launcher plugins. Stripped for both the shown
# title and the merge key so "GFN - Enshrouded" collapses into "Enshrouded".
_SOURCE_TITLE_PREFIXES = (
    "gfn - ",
    "gfn – ",
    "gfn — ",
    "gfn-",
    "gfn –",
    "geforce now - ",
    "geforce now – ",
    "geforce now — ",
    "geforce now: ",
    "geforce now ",
)


def strip_source_title_prefix(title: str) -> str:
    """Remove a leading 'GFN - ' / 'GeForce NOW' prefix (any common dash)."""
    t = (title or "").strip()
    changed = True
    while t and changed:
        changed = False
        lower = t.casefold()
        for prefix in _SOURCE_TITLE_PREFIXES:
            if lower.startswith(prefix):
                t = t[len(prefix) :].strip()
                changed = True
                break
    return t


def normalize_title(title: str) -> str:
    t = strip_source_title_prefix(title).casefold().strip()
    for suffix in (
        " game of the year edition",
        " definitive edition",
        " complete edition",
        " ultimate edition",
        " deluxe edition",
        " goty edition",
        " remastered",
        " remake",
    ):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return _TITLE_STRIP.sub("", t)


@dataclass
class LaunchSpec:
    kind: str  # argv | uri | desktop
    value: str | list[str]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.cwd:
            d["cwd"] = self.cwd
        if self.env:
            d["env"] = self.env
        return d


@dataclass
class TrackSpec:
    window_class: str | None = None
    steam_app_id: int | None = None
    handoff: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "windowClass": self.window_class,
            "steamAppId": self.steam_app_id,
            "handoff": self.handoff,
        }


@dataclass
class ArtSpec:
    cover: str | None = None
    hero: str | None = None
    logo: str | None = None
    icon: str | None = None
    icon_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = {
            "cover": self.cover,
            "hero": self.hero,
            "logo": self.logo,
            "icon": self.icon,
        }
        if self.icon_only:
            d["iconOnly"] = True
        return d


@dataclass
class Game:
    id: str
    title: str
    source: str
    store: str | None = None
    runner: str = "native"
    platform: str | None = None
    installed: bool = True
    launch: LaunchSpec | None = None
    track: TrackSpec = field(default_factory=TrackSpec)
    art: ArtSpec = field(default_factory=ArtSpec)
    steam_app_id: int | None = None
    playtime_minutes: int | None = None
    last_played: str | None = None
    dedupe_keys: list[str] = field(default_factory=list)
    also_on: list[Any] = field(default_factory=list)
    description: str | None = None

    def __post_init__(self) -> None:
        if self.source == "gfn":
            self.title = strip_source_title_prefix(self.title)
        if not self.dedupe_keys:
            keys = [f"title:{normalize_title(self.title)}"]
            if self.steam_app_id:
                keys.append(f"steam:{self.steam_app_id}")
            self.dedupe_keys = keys

    @property
    def sort_title(self) -> str:
        t = self.title.casefold().strip()
        if t.startswith("the "):
            t = t[4:]
        return t

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "sortTitle": self.sort_title,
            "source": self.source,
            "store": self.store,
            "runner": self.runner,
            "platform": self.platform,
            "installed": self.installed,
            "launch": self.launch.to_dict() if self.launch else None,
            "track": self.track.to_dict(),
            "art": self.art.to_dict(),
            "steamAppId": self.steam_app_id,
            "playtimeMinutes": self.playtime_minutes,
            "lastPlayed": self.last_played,
            "dedupeKeys": self.dedupe_keys,
            "alsoOn": self.also_on,
            "description": self.description,
        }


@dataclass
class ScanError:
    source: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "error": self.error}


def also_on_payload(game: Game) -> dict[str, Any]:
    """Launchable alternate source for the Play on… picker."""
    return {
        "id": game.id,
        "source": game.source,
        "store": game.store,
        "title": game.title,
        "launch": game.launch.to_dict() if game.launch else None,
        "track": game.track.to_dict(),
    }


def _also_on_id(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("id")
    return None


def _has_also_on(entries: list[Any], game_id: str) -> bool:
    return any(_also_on_id(e) == game_id for e in entries)


def _launch_text(game: Game) -> str:
    if not game.launch:
        return ""
    value = game.launch.value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(p) for p in value)
    return str(value)


def is_steam_desktop_wrapper(game: Game) -> bool:
    """True for Steam's own .desktop shortcuts (steam://rungameid or generated)."""
    if game.source == "steam":
        return False
    if game.steam_app_id and game.source == "desktop":
        return True
    text = _launch_text(game).casefold()
    if "steam://rungameid/" in text:
        return True
    gid = (game.id or "").casefold()
    return gid.startswith("desktop:steam:") or gid.startswith("steam_app_")


def should_record_also_on(keeper: Game, other: Game) -> bool:
    """Play on… only for real alternate stores, not Steam .desktop wrappers."""
    if keeper.source == other.source:
        return False
    if is_steam_desktop_wrapper(other) or is_steam_desktop_wrapper(keeper):
        return False
    if keeper.steam_app_id and other.steam_app_id and keeper.steam_app_id == other.steam_app_id:
        if "desktop" in {keeper.source, other.source}:
            return False
    return True


def _absorb_art(dst: Game, src: Game) -> None:
    if src.art.cover and (not dst.art.cover or (dst.art.icon_only and not src.art.icon_only)):
        dst.art.cover = src.art.cover
        dst.art.icon_only = bool(src.art.icon_only)
    if not dst.art.hero and src.art.hero:
        dst.art.hero = src.art.hero
    if not dst.art.icon and src.art.icon:
        dst.art.icon = src.art.icon


def merge_games(games: list[Game]) -> list[Game]:
    """Collapse duplicates. Prefer richer sources over bare .desktop wrappers."""
    source_rank = {
        "steam": 0,
        "heroic": 1,
        "legendary": 2,
        "lutris": 3,
        "bottles": 4,
        "itch": 5,
        "gfn": 6,
        "retroarch": 7,
        "roms": 8,
        "moonlight": 9,
        "webapp": 10,
        "desktop": 11,
    }
    by_key: dict[str, Game] = {}
    order: list[str] = []

    for game in games:
        primary = None
        for key in game.dedupe_keys:
            if key in by_key:
                primary = by_key[key]
                break
        if primary is None:
            for key in game.dedupe_keys:
                by_key[key] = game
            order.append(game.dedupe_keys[0])
            continue

        # Prefer non-desktop over desktop wrappers; keep higher-ranked source.
        if source_rank.get(game.source, 99) < source_rank.get(primary.source, 99):
            if should_record_also_on(game, primary) and not _has_also_on(game.also_on, primary.id):
                game.also_on = [*game.also_on, also_on_payload(primary)]
            _absorb_art(game, primary)
            if game.playtime_minutes is None and primary.playtime_minutes is not None:
                game.playtime_minutes = primary.playtime_minutes
            if not game.last_played and primary.last_played:
                game.last_played = primary.last_played
            for key in game.dedupe_keys:
                by_key[key] = game
            # Replace order entry
            for i, k in enumerate(order):
                if by_key.get(k) is primary or k in primary.dedupe_keys:
                    order[i] = game.dedupe_keys[0]
                    break
        else:
            if should_record_also_on(primary, game) and not _has_also_on(primary.also_on, game.id):
                primary.also_on = [*primary.also_on, also_on_payload(game)]
            _absorb_art(primary, game)
            if primary.playtime_minutes is None and game.playtime_minutes is not None:
                primary.playtime_minutes = game.playtime_minutes
            if not primary.last_played and game.last_played:
                primary.last_played = game.last_played
            for key in game.dedupe_keys:
                by_key[key] = primary

    seen: set[str] = set()
    result: list[Game] = []
    for key in order:
        g = by_key[key]
        if g.id in seen:
            continue
        seen.add(g.id)
        result.append(g)
    result.sort(key=lambda g: g.sort_title)
    return result


def parse_library_text(text: str | None) -> dict[str, Any]:
    """Parse library.json text the same way the overlay fallback does."""
    if not text or not str(text).strip():
        return {"games": [], "errors": [], "ok": True, "empty": True}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"games": [], "errors": [], "ok": False, "empty": True, "error": str(exc)}
    games = data.get("games") or []
    return {
        "games": games,
        "errors": data.get("errors") or [],
        "ok": True,
        "empty": len(games) == 0,
    }


def resolved_games(service_games: list[Any] | None, local_games: list[Any] | None) -> list[Any]:
    """Prefer an in-memory service library; fall back to the on-disk cache."""
    if service_games:
        return list(service_games)
    return list(local_games or [])


def write_library(path: Path, games: list[Game], errors: list[ScanError]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "games": [g.to_dict() for g in games],
        "errors": [e.to_dict() for e in errors],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_library(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "games": [], "errors": []}
    return json.loads(path.read_text(encoding="utf-8"))
