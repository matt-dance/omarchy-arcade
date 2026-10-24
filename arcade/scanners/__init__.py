"""Library scanners for each game source."""

from __future__ import annotations

from typing import Callable

from ..config import ArcadeConfig
from ..model import Game, ScanError, merge_games
from . import bottles, desktop, heroic, itch, legendary, lutris, retroarch, roms, steam

ScanFn = Callable[[], tuple[list[Game], list[ScanError]]]

SCANNERS: dict[str, ScanFn] = {
    "steam": steam.scan,
    "heroic": heroic.scan,
    "legendary": legendary.scan,
    "lutris": lutris.scan,
    "bottles": bottles.scan,
    "itch": itch.scan,
    "desktop": desktop.scan,
    "retroarch": retroarch.scan,
    "roms": roms.scan,
}


def run_all(cfg: ArcadeConfig | None = None) -> tuple[list[Game], list[ScanError]]:
    games: list[Game] = []
    errors: list[ScanError] = []
    sources = cfg.sources if cfg else {}
    for name, fn in SCANNERS.items():
        if cfg is not None and not cfg.source_enabled(name):
            continue
        if cfg is None and sources.get(name) is False:
            continue
        try:
            found, errs = fn()
        except Exception as exc:  # noqa: BLE001 — scanners must never kill the run
            errors.append(ScanError(source=name, error=str(exc)))
            continue
        games.extend(found)
        errors.extend(errs)
    return merge_games(games), errors
