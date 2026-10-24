"""Unified game model and library merge helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_TITLE_STRIP = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    t = title.casefold().strip()
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    also_on: list[str] = field(default_factory=list)
    description: str | None = None

    def __post_init__(self) -> None:
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
            if primary.id not in game.also_on:
                game.also_on = list(dict.fromkeys([*game.also_on, primary.id]))
            for key in game.dedupe_keys:
                by_key[key] = game
            # Replace order entry
            for i, k in enumerate(order):
                if by_key.get(k) is primary or k in primary.dedupe_keys:
                    order[i] = game.dedupe_keys[0]
                    break
        else:
            if game.id not in primary.also_on and game.source != primary.source:
                primary.also_on = list(dict.fromkeys([*primary.also_on, game.id]))
            # Absorb art / playtime when missing
            if not primary.art.cover and game.art.cover:
                primary.art.cover = game.art.cover
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
